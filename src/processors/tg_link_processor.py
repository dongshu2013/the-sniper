import logging
from urllib.parse import urlparse

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient

from src.common.types import TgLinkStatus
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TgLinkProcessor(ProcessorBase):
    def __init__(
        self, client: TelegramClient, redis_client: Redis, pg_conn: asyncpg.Connection
    ):
        super().__init__(interval=30)
        self.client = client
        self.redis_client = redis_client
        self.pg_conn = pg_conn

    async def process(self):
        select_query = """
            SELECT id, tg_link, status
            FROM tg_link_status
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """
        item = await self.pg_conn.fetchrow(select_query)
        if not item:
            return

        tg_link = item["tg_link"].strip()
        if item["status"] is not None:
            logger.info(f"Group {tg_link} already processed")
            return

        logger.info(f"Processing group: {tg_link}")
        status, chat_id = await self.get_chat_id_from_link(tg_link)
        await self.pg_conn.execute(
            """UPDATE tg_link_status
            SET status = $1, chat_id = $2, processed_at = CURRENT_TIMESTAMP
            WHERE id = $3""",
            status.value,
            chat_id,
            item["id"],
        )

    async def get_chat_id_from_link(
        self, tme_link: str
    ) -> tuple[TgLinkStatus, str | None]:
        parsed = urlparse(tme_link)
        path = parsed.path.strip("/")
        try:
            if path.startswith("+") or "joinchat" in path:
                entity = await self.client.get_entity(tme_link)  # invite
            else:
                entity = await self.client.get_entity(f"t.me/{path}")
        except Exception as e:
            logger.error(f"Failed to get entity from link {tme_link}: {e}")
            return TgLinkStatus.ERROR.value, None

        logger.info(f"Fetched entity: {entity}")
        is_valid = (
            hasattr(entity, "broadcast")  # channels
            or hasattr(entity, "megagroup")  # supergroups
            or getattr(entity, "chat", False)  # normal groups
        )
        if not is_valid:
            logger.info(f"Group {tme_link} is not a group")
            return TgLinkStatus.IGNORED.value, None

        chat_id = str(entity.id)
        if chat_id.startswith("-100"):
            chat_id = chat_id[4:]
        elif chat_id.startswith("-"):
            chat_id = chat_id[1:]
        return TgLinkStatus.PROCESSED.value, chat_id
