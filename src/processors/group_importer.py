import asyncio
import logging
import time
from urllib.parse import urlparse

import asyncpg
from pydantic import BaseModel
from redis.asyncio import Redis
from telethon import TelegramClient

from src.common.config import chat_indexed_key

logger = logging.getLogger(__name__)


class ChatMetadata(BaseModel):
    chat_id: str
    name: str
    about: str
    participants_count: int
    processed_at: int


class GroupImporter:
    def __init__(
        self, client: TelegramClient, redis_client: Redis, pg_conn: asyncpg.Connection
    ):
        self.client = client
        self.redis_client = redis_client
        self.pg_conn = pg_conn
        self.running = False
        self.interval = 300

    async def start_processing(self):
        self.running = True
        while self.running:
            try:
                await self.process_groups()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in group processing: {e}")

    async def stop_processing(self):
        self.running = False

    async def process_groups(self):
        """Process unprocessed groups from chat metadata table"""
        try:
            # Get unprocessed groups from database
            async with self.pg_conn.acquire() as conn:
                unprocessed = await conn.fetch(
                    """
                    SELECT id, tme_link
                    FROM chat_metadata
                    WHERE processed_at IS NULL
                    LIMIT 50
                    """
                )

                for record in unprocessed:
                    try:
                        # Get group info from Telegram
                        group_info = await self.get_info_from_link(record["tme_link"])

                        if group_info:
                            # Update database with processed info
                            await conn.execute(
                                """
                                UPDATE chat_metadata
                                SET chat_id = $1,
                                    name = $2,
                                    about = $3,
                                    participants_count = $4,
                                    processed_at = $5
                                WHERE id = $6
                                """,
                                group_info.chat_id,
                                group_info.name,
                                group_info.about,
                                group_info.participants_count,
                                int(time.time()),
                                record["id"],
                            )
                            await self.redis_client.set(
                                chat_indexed_key(group_info.chat_id), int(time.time())
                            )
                            logger.info(f"Processed group {group_info.name}")
                    except Exception as e:
                        logger.error(
                            f"Error processing group {record['tme_link']}: {e}"
                        )
                        await conn.execute(
                            "UPDATE chat_metadata SET processed_at = $1 WHERE id = $2",
                            -1,
                            record["id"],
                        )
        except Exception as e:
            logger.error(f"Database error in process_groups: {e}")

    async def get_info_from_link(self, tme_link: str) -> ChatMetadata | None:
        parsed = urlparse(tme_link)
        path = parsed.path.strip("/")
        if path.startswith("+") or "joinchat" in path:
            entity = await self.client.get_entity(tme_link)  # invite
        else:
            entity = await self.client.get_entity(f"t.me/{path}")
        return ChatMetadata(
            chat_id=entity.id,
            name=entity.title,
            about=entity.about,
            participants_count=entity.participants_count,
            processed_at=int(time.time()),
        )
