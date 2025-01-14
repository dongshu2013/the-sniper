import asyncio
import logging
from urllib.parse import urlparse

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest

from src.common.config import (
    PENDING_TG_GROUPS_KEY,
    chat_watched_by_key,
    tg_link_status_key,
)
from src.common.types import ChatMetadata, EntityGroupItem
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class GroupQueueProcessor(ProcessorBase):
    def __init__(
        self, client: TelegramClient, redis_client: Redis, pg_conn: asyncpg.Connection
    ):
        super().__init__(interval=30)
        self.client = client
        self.redis_client = redis_client
        self.pg_conn = pg_conn

    async def process(self):
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

        logger.info(f"Processing group: {item.telegram_link}")
        chat_id = await self.get_chat_id_from_link(item.telegram_link)
        if not chat_id:
            await self.redis_client.set(link_status_key, "error")
            return

        await self.update_entity_id(str(chat_id), item.entity_id)
        success = await self.try_to_join_channel(item.entity_id, chat_id)
        if success:
            await self.redis_client.set(link_status_key, "success")

    async def get_chat_id_from_link(self, tme_link: str) -> str | None:
        parsed = urlparse(tme_link)
        path = parsed.path.strip("/")
        try:
            if path.startswith("+") or "joinchat" in path:
                entity = await self.client.get_entity(tme_link)  # invite
            else:
                entity = await self.client.get_entity(f"t.me/{path}")
        except Exception as e:
            logger.error(f"Failed to get entity from link {tme_link}: {e}")
            return None

        logger.info(f"Fetched entity: {entity}")
        is_valid = (
            hasattr(entity, "broadcast")  # channels
            or hasattr(entity, "megagroup")  # supergroups
            or getattr(entity, "chat", False)  # normal groups
        )
        if not is_valid:
            logger.info(f"Group {tme_link} is not a group")
            return None
        return entity.id

    async def try_to_join_channel(self, entity_id: int, chat_id: int):
        watchers = await self.redis_client.llen(chat_watched_by_key(chat_id))
        if watchers > 0:
            logger.info(f"Group {chat_id} already watched by other bots")
            return  # already watched by other bots

        try:
            logger.info(f"Joining group {chat_id}")
            await self.client(JoinChannelRequest(chat_id))
            me = await self.client.get_me()
            await self.redis_client.lpush(chat_watched_by_key(chat_id), me.id)
            return True
        except Exception as e:
            logger.error(f"Failed to join channel {chat_id}: {e}")
            # Check if this is a flood wait error
            if "wait of" in str(e).lower():
                # Re-queue the group by pushing it back to the pending queue
                group_item = EntityGroupItem(
                    telegram_link=f"https://t.me/c/{chat_id}",
                    entity_id=entity_id,
                )
                await self.redis_client.lpush(
                    PENDING_TG_GROUPS_KEY, group_item.model_dump_json()
                )
                logger.info(f"Re-queued group {chat_id} due to rate limit")
                logger.info("Waiting for 2000 seconds")
                await asyncio.sleep(2000)
            return False

    async def update_entity_id(
        self,
        chat_id: str,
        entity_id: int,
    ) -> ChatMetadata | str:
        try:
            await self.pg_conn.execute(
                """
                INSERT INTO chat_metadata (chat_id, entity_id)
                VALUES ($1, $2)
                ON CONFLICT (chat_id) DO UPDATE
                SET entity_id = EXCLUDED.entity_id
                """,
                chat_id,
                entity_id,
            )
        except Exception as e:
            logger.error(f"Database error in update_entity_id: {e}")
