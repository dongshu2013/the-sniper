import asyncio
import json
import logging

import psycopg2

from src.config import DATABASE_URL, SERVICE_PREFIX  # Add DATABASE_URL to config

logger = logging.getLogger(__name__)


class MessageProcessor:
    def __init__(
        self,
        interval,
        redis_client,
        batch_size=1000,
    ):
        self.interval = interval
        self.running = False
        self.redis_client = redis_client
        self.batch_size = batch_size
        self.conn = None

    async def start_processing(self):
        # Create PostgreSQL connection
        try:
            self.conn = psycopg2.connect(DATABASE_URL)

            # Create messages table if it doesn't exist
            with self.conn.cursor() as cur:
                cur.execute(
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
            self.conn.commit()
        except psycopg2.Error as e:
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
        messages_by_chat = {}

        try:
            # Get all chat keys
            chat_pattern = f"{SERVICE_PREFIX}:chat:*:messages"
            chat_keys = await self.redis_client.keys(chat_pattern)

            for chat_key in chat_keys:
                chat_id = chat_key.decode().split(":")[2]
                messages_by_chat[chat_id] = []
                while True:
                    messages = await self.redis_client.lpop(chat_key, self.batch_size)
                    if not messages:
                        break
                    messages_by_chat[chat_id].extend(messages)
                    if len(messages) < self.batch_size:
                        break
            total_messages = sum(
                len(messages) for messages in messages_by_chat.values()
            )
            logger.info(
                f"Retrieved {total_messages} messages "
                f"from {len(messages_by_chat)} chats"
            )
            if messages_by_chat:
                await self._save_to_database(messages_by_chat)

        except Exception as e:
            logger.error(f"Error reading group data: {e}")
            return {}

    async def _save_to_database(self, messages_by_chat):
        try:
            with self.conn.cursor() as cur:
                for chat_id, messages in messages_by_chat.items():
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
                    cur.executemany(
                        """
                        INSERT INTO chat_messages
                            (message_id, chat_id, message_text,
                             sender_id, message_timestamp)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (chat_id, message_id) DO NOTHING
                        """,
                        values,
                    )
                self.conn.commit()
                logger.info(
                    f"Successfully inserted {len(messages)} messages for chat {chat_id}"
                )

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to save data to database: {e}")
            raise

    async def stop_processing(self):
        self.running = False
        if self.conn:
            self.conn.close()
