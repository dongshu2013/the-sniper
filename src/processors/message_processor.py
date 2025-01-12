import asyncio
import json
import logging

import asyncpg
from redis import Redis

from config import (
    DATABASE_URL,
    PROCESSING_INTERVAL,
    REDIS_URL,
    SERVICE_PREFIX,
    chat_per_hour_stats_key,
)

logger = logging.getLogger(__name__)
logger.basicConfig(level=logging.INFO)


class MessageProcessor:
    def __init__(self):
        self.running = False
        self.interval = PROCESSING_INTERVAL
        self.redis_client = Redis.from_url(REDIS_URL)
        self.conn = None

    async def start_processing(self):
        try:
            self.conn = await asyncpg.connect(DATABASE_URL)
            await self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    message_timestamp BIGINT NOT NULL,
                    created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
                    UNIQUE (chat_id, message_id)
                )
            """
            )
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise

        self.running = True
        while self.running:
            try:
                await self.process_messages()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in message processing: {e}")

    async def process_messages(self):
        try:
            # Get all chat keys
            logging.info("loading chat keys")
            chat_pattern = f"{SERVICE_PREFIX}:chat:*:messages"
            chat_keys = await self.redis_client.keys(chat_pattern)
            logging.info(f"loaded {len(chat_keys)} chat keys")

            logging.info("loading messages from chats")
            # First pipeline: Get all messages
            pipeline = self.redis_client.pipeline()
            for chat_key in chat_keys:
                pipeline.lrange(chat_key, 0, -1)
            all_messages = await pipeline.execute()
            logging.info(f"loaded {len(all_messages.flatten())} messages")

            # Second pipeline: Process and increment counters
            logging.info(f"Processing {len(all_messages)} chats")
            pipeline = self.redis_client.pipeline()
            messages_per_chat = {}
            for chat_key, messages in zip(chat_keys, all_messages):
                if not messages:
                    continue
                chat_id = chat_key.decode().split(":")[2]
                messages_per_chat[chat_id] = messages
                pipeline.incr(
                    chat_per_hour_stats_key(chat_id, "num_of_messages"),
                    len(messages),
                )
            await pipeline.execute()
            logging.info(f"processed {len(messages_per_chat)} chats")

            logging.info(f"Saving {len(messages_per_chat)} chats")
            async with self.conn.transaction():
                for chat_id, messages in messages_per_chat.items():
                    await self.save_one_chat(chat_id, messages)
            logging.info(f"saved {len(messages_per_chat)} chats")

        except Exception as e:
            logger.error(f"Error reading group data: {e}")

    async def save_one_chat(self, chat_id: int, messages: list[str]):
        values = []
        for msg in messages:
            message_data = json.loads(msg.decode())
            values.append(
                (
                    int(message_data["message_id"]),
                    int(chat_id),
                    message_data["message"],
                    int(message_data["sender"]),
                    int(message_data["timestamp"]),
                )
            )

        # Perform batch insert, ignore duplicates
        await self.conn.executemany(
            """
            INSERT INTO chat_messages
                (message_id, chat_id, message_text,
                    sender_id, message_timestamp)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (chat_id, message_id) DO NOTHING
            """,
            values,
        )

    async def stop_processing(self):
        self.running = False
        if self.conn:
            await self.conn.close()
