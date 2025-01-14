import asyncio
import logging
import time
from urllib.parse import urlparse

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient

from src.common.config import (
    PENDING_TG_GROUPS_KEY,
    chat_watched_by_key,
    tg_link_status_key,
)
from src.common.types import ChatMetadata, EntityGroupItem

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GroupImporter:
    def __init__(
        self, client: TelegramClient, redis_client: Redis, pg_conn: asyncpg.Connection
    ):
        self.client = client
        self.redis_client = redis_client
        self.pg_conn = pg_conn
        self.running = False
        self.interval = 10
        self.dialogs = {}
        self.me = None

    async def start_processing(self):
        self.running = True
        dialogs = await self.client.get_dialogs(archived=False)
        self.dialogs = {d.id: d for d in dialogs if d.is_group or d.is_channel}
        self.me = await self.client.get_me()
        while self.running:
            try:
                await self.process()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in group processing: {e}")

    async def stop_processing(self):
        self.running = False

    async def process(self):
        """Process unprocessed groups from chat metadata table"""
        item = await self.redis_client.rpop(PENDING_TG_GROUPS_KEY)
        if not item:
            return
        item = EntityGroupItem.model_validate_json(item)
        item.telegram_link = item.telegram_link.strip()

        link_status_key = tg_link_status_key(item.telegram_link)
        status = await self.redis_client.get(link_status_key)
        if status is not None:
            logger.info(f"Group {item.telegram_link} already processed")
            return

        result = await self.fetch_and_store_group_info(item)
        await self.redis_client.set(
            link_status_key, "success" if result["success"] else result["error"]
        )
        if result["success"]:
            await self.try_to_join_channel(result["metadata"])

    async def fetch_and_store_group_info(
        self, item: EntityGroupItem
    ) -> ChatMetadata | str:
        try:
            logger.info(f"Fetching group info for {item.telegram_link}")
            metadata = await self.get_info_from_link(item.telegram_link)
            if not metadata:
                return {"success": False, "error": "not_a_group"}
            await self.pg_conn.execute(
                """
                INSERT INTO chat_metadata (
                    chat_id, name, about, participants_count,
                    processed_at, entity_id
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (chat_id) DO UPDATE
                SET name = EXCLUDED.name,
                    about = EXCLUDED.about,
                    participants_count = EXCLUDED.participants_count,
                    processed_at = EXCLUDED.processed_at
                """,
                metadata.chat_id,
                metadata.name,
                metadata.about,
                metadata.participants_count,
                int(time.time()),
                item.entity_id,
            )
            logger.info(f"Group {metadata.chat_id} processed successfully")
            return {"success": True, "metadata": metadata}
        except Exception as e:
            logger.error(f"Database error in fetch_and_store_group_info: {e}")
            return {"success": False, "error": "unknown_error"}

    async def get_info_from_link(self, tme_link: str) -> ChatMetadata | None:
        parsed = urlparse(tme_link)
        path = parsed.path.strip("/")
        if path.startswith("+") or "joinchat" in path:
            entity = await self.client.get_entity(tme_link)  # invite
        else:
            entity = await self.client.get_entity(f"t.me/{path}")
        if not entity.is_channel and not entity.is_group:
            return None
        return ChatMetadata(
            chat_id=entity.id,
            name=entity.title,
            about=entity.about,
            participants_count=entity.participants_count,
            processed_at=int(time.time()),
        )

    async def try_to_join_channel(self, metadata: ChatMetadata):
        if metadata.chat_id in self.dialogs:
            logger.info(f"Group {metadata.chat_id} already joined")
            return  # already joined

        watchers = await self.redis_client.llen(chat_watched_by_key(metadata.chat_id))
        if watchers > 0:
            logger.info(f"Group {metadata.chat_id} already watched by other bots")
            return  # already watched by other bots

        try:
            logger.info(f"Joining group {metadata.chat_id}")
            await self.client.join_chat(metadata.chat_id)
            await self.redis_client.lpush(
                chat_watched_by_key(metadata.chat_id), self.me.id
            )
        except Exception as e:
            logger.error(f"Failed to join channel {metadata.chat_id}: {e}")
