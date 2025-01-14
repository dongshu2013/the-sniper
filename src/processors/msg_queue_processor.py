import json
import logging
from typing import Dict, List

import asyncpg
from pydantic import ValidationError
from redis.asyncio import Redis

from src.common.config import MESSAGE_QUEUE_KEY
from src.common.types import ChatMessage
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class MessageQueueProcessor(ProcessorBase):
    def __init__(
        self,
        redis_client: Redis,
        pg_conn: asyncpg.Connection,
        batch_size: int = 100,
    ):
        super().__init__(interval=1)
        self.redis_client = redis_client
        self.pg_conn = pg_conn
        self.batch_size = batch_size

    async def process(self) -> int:
        messages: List[Dict] = []

        # Get batch of messages from Redis in a single operation
        raw_messages = await self.redis_client.rpop(MESSAGE_QUEUE_KEY, self.batch_size)
        if not raw_messages:
            return 0

        # Convert to list if single item is returned
        if not isinstance(raw_messages, list):
            raw_messages = [raw_messages]

        # Process messages
        logger.info(f"will process {len(raw_messages)} raw messages")
        for message in raw_messages:
            try:
                messages.append(ChatMessage.model_validate_json(message))
            except ValidationError:
                logger.error(f"Failed to decode message: {message}")
                continue

        if not messages:
            return 0

        logger.info(f"will process {len(messages)} messages")
        try:
            await self.pg_conn.executemany(
                """
                INSERT INTO chat_messages
                        (message_id, chat_id, message_text,
                         sender_id, message_timestamp)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (chat_id, message_id) DO NOTHING
                    """,
                [
                    (
                        m.message_id,
                        m.chat_id,
                        m.message_text,
                        m.sender_id,
                        m.message_timestamp,
                    )
                    for m in messages
                ],
            )
            logger.info(f"Processed {len(messages)} messages")
            return len(messages)
        except Exception as e:
            logger.error(f"Database error: {e}")
            # Optionally, push failed messages back to Redis
            for msg in messages:
                await self.redis_client.lpush(MESSAGE_QUEUE_KEY, json.dumps(msg))
            return 0
