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
                chat_id = str(dialog.id)
                if chat_id.startswith("-100"):
                    chat_id = chat_id[4:]

                logger.info(f"Updating group {chat_id} with name {dialog.name}")
                updates.append(
                    (
                        chat_id,  # normalized chat_id
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
                INSERT INTO chat_metadata (
                    chat_id, name, about, username, participants_count, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, CURRENT_TIMESTAMP
                )
                ON CONFLICT (chat_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    about = EXCLUDED.about,
                    username = EXCLUDED.username,
                    participants_count = EXCLUDED.participants_count,
                    updated_at = CURRENT_TIMESTAMP
                """,
                updates,
            )
            logger.info(f"Processed {len(updates)} groups successfully")
