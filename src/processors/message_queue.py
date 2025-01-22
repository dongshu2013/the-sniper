import json
import logging
from typing import Dict, List

import asyncpg
from pydantic import ValidationError
from redis.asyncio import Redis

from src.common.config import DATABASE_URL, MESSAGE_QUEUE_KEY, REDIS_URL
from src.common.types import ChatMessage
from src.helpers.message_helper import store_messages
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class MessageQueueProcessor(ProcessorBase):
    def __init__(
        self,
        batch_size: int = 100,
    ):
        super().__init__(interval=1)
        self.batch_size = batch_size
        self.redis_client = Redis.from_url(REDIS_URL)
        self.pg_conn = None

    async def process(self) -> int:
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        messages: List[Dict] = []

        # Get batch of messages from Redis in a single operation
        raw_messages = await self.redis_client.rpop(MESSAGE_QUEUE_KEY, self.batch_size)
        if not raw_messages:
            return 0

        # Convert to list if single item is returned
        if not isinstance(raw_messages, list):
            raw_messages = [raw_messages]

        # Process messages
        for message in raw_messages:
            try:
                # First decode bytes to string properly
                if isinstance(message, bytes):
                    message = message.decode("utf-8")

                # Then parse JSON
                messages.append(ChatMessage.model_validate_json(message))
            except (UnicodeDecodeError, ValidationError) as e:
                logger.error(f"Failed to decode message: {message}", exc_info=e)
                continue

        if not messages:
            return 0

        # Optionally, push failed messages back to Redis
        processed = await store_messages(self.pg_conn, messages)
        if processed != len(messages):
            for msg in messages:
                await self.redis_client.lpush(MESSAGE_QUEUE_KEY, json.dumps(msg))
