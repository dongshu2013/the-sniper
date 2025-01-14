import logging

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient

from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class GroupInfoUpdater(ProcessorBase):
    def __init__(
        self, client: TelegramClient, redis_client: Redis, pg_conn: asyncpg.Connection
    ):
        super().__init__(interval=300)
        self.client = client
        self.redis_client = redis_client
        self.pg_conn = pg_conn

    async def process(self):
        updates = []
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            if dialog.is_group or dialog.is_channel:
                updates.append(
                    (
                        str(dialog.id),  # chat_id
                        dialog.name or None,  # name
                        getattr(dialog.entity, "about", None),  # about
                        getattr(dialog.entity, "username", None),  # username
                        getattr(
                            dialog.entity, "participants_count", 0
                        ),  # participants_count
                    )
                )
        if updates:
            await self.pg_conn.executemany(
                """
                UPDATE chat_metadata SET
                    name = $2,
                    about = $3,
                    username = $4,
                    participants_count = $5,
                    updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = $1
                """,
                updates,
            )
            logger.info(f"Processed {len(updates)} groups successfully")
