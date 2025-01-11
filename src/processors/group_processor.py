import asyncio
import json
import logging
import time
from enum import Enum

from redis.asyncio import Redis
from telethon import TelegramClient, types

from src.config import REDIS_URL, chat_info_key, chat_watchers_key, user_chat_key

logger = logging.getLogger(__name__)


MIN_PARTICIPANTS = 50
MIN_WATCHERS = 2


class ChatStatus(Enum):
    ACTIVE = "active"
    NOT_ENOUGH_PARTICIPANTS = "not_enough_participants"
    NOT_RELATED_TOPIC = "not_related_topic"
    ENOUGH_WATCHERS = "enough_watchers"


class ChatProcessor:
    def __init__(self, client: TelegramClient, interval: int):
        self.client = client
        self.interval = interval
        self.running = False
        self.force = False
        self.redis_client = Redis.from_url(REDIS_URL)

    async def start_processing(self):
        self.running = True
        while self.running:
            try:
                await self.process_groups()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in group processing: {e}")

    async def process_groups(self):
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            me = await self.client.get_me()
            if not await should_watch_chat(self.redis_client, me, dialog):
                continue

            chat_id = str(dialog.id)
            pipeline = self.redis_client.pipeline()
            pipeline.set(
                user_chat_key(me.id, chat_id),
                json.dumps(
                    {
                        "status": ChatStatus.ACTIVE.value,
                        "processed_at": int(time.time()),
                    }
                ),
            )
            pipeline.set(
                chat_info_key(chat_id),
                json.dumps(
                    {
                        "name": dialog.name,
                        "participants_count": dialog.entity.participants_count,
                    }
                ),
            )
            pipeline.lpush(chat_watchers_key(chat_id), me.id)
            await pipeline.execute()

    async def stop_processing(self):
        self.running = False


async def should_watch_chat(
    redis_client: Redis,
    me: types.User,
    dialog: types.Dialog,
):
    if not dialog.is_group and not dialog.is_channel:
        return False

    chat_id = str(dialog.id)
    status, watchers = await redis_client.mget(
        user_chat_key(me.id, chat_id),
        chat_watchers_key(chat_id),
    )
    # already processed
    if status is not None:
        return False

    # not enough participants
    if dialog.entity.participants_count < MIN_PARTICIPANTS:
        await set_chat_status(
            redis_client, me.id, chat_id, ChatStatus.NOT_ENOUGH_PARTICIPANTS
        )
        return False

    # already watched
    watchers = [] if watchers is None else json.loads(watchers)
    if me.id in watchers:
        return False

    # already watched by enough accounts
    if len(watchers) >= MIN_WATCHERS:
        await set_chat_status(redis_client, me.id, chat_id, ChatStatus.ENOUGH_WATCHERS)
        return False

    return True


async def get_chat_info(redis_client: Redis, chat_id: str) -> dict | None:
    value = await redis_client.get(chat_info_key(chat_id))
    return json.loads(value) if value else None


async def set_chat_status(
    redis_client: Redis, user_id: str, chat_id: str, status: ChatStatus
):
    await redis_client.set(
        user_chat_key(user_id, chat_id),
        json.dumps(
            {
                "status": status.value,
                "processed_at": int(time.time()),
            }
        ),
    )
