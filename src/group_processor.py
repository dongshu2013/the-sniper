import asyncio
import json
import logging
from enum import Enum

from redis import Pipeline
from telethon import TelegramClient, types

from src.config import SERVICE_PREFIX, redis_client

logger = logging.getLogger(__name__)


MIN_PARTICIPANTS = 50
MIN_WATCHERS = 2


class ChatStatus(Enum):
    ACTIVE = "active"
    NOT_ENOUGH_PARTICIPANTS = "not_enough_participants"
    NOT_RELATED_TOPIC = "not_related_topic"


class ChatProcessor:
    def __init__(self, client: TelegramClient, interval: int):
        self.client = client
        self.interval = interval
        self.running = False
        self.force = False

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
            if not dialog.is_group and not dialog.is_channel:
                continue

            me = await self.client.get_me()
            chat_id = str(dialog.id)
            processed = await redis_client.get(user_chat_key(me.id, chat_id))
            if processed == "true" and not self.force:
                continue  # already processed

            pipeline = redis_client.pipeline()
            await try_watch_group_or_channel(me, dialog, pipeline)
            await pipeline.set(
                chat_info_key(chat_id),
                json.dumps(
                    {
                        "name": dialog.name,
                        "id": dialog.id,
                        "participants_count": dialog.entity.participants_count,
                    }
                ),
            )
            await pipeline.set(user_chat_key(me.id, chat_id), "true")
            await pipeline.execute()

    async def stop_processing(self):
        self.running = False


async def try_watch_group_or_channel(
    me: types.User,
    dialog: types.Dialog,
    pipeline: Pipeline,
):
    chat_id = str(dialog.id)

    # group is disabled by other watchers
    if await is_chat_disabled(chat_id):
        return False

    watchers = await get_watchers(chat_id)
    # already watched by this account
    if me.id in watchers:
        return True

    # already watched by enough accounts
    if len(watchers) >= MIN_WATCHERS:
        return False

    if dialog.entity.participants_count >= MIN_PARTICIPANTS:
        logger.info(f"Watching group/channel: {dialog.name}")
        pipeline.lpush(chat_watchers_key(chat_id), me.id)
        return True
    else:
        logger.info(
            "Group/channel not enough participants: "
            f"{dialog.name} with {dialog.entity.participants_count} participants"
        )
        # we can have cron job to re-check disabled groups
        pipeline.set(chat_status_key(chat_id), ChatStatus.NOT_ENOUGH_PARTICIPANTS.value)
        return False


def chat_watchers_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:watchers"


def chat_info_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:info"


def chat_status_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:status"


def user_chat_key(user_id: str, chat_id: str):
    return f"{SERVICE_PREFIX}:user:{user_id}:chat:{chat_id}"


async def get_chat_info(chat_id: str) -> dict | None:
    value = await redis_client.get(chat_info_key(chat_id))
    return json.loads(value) if value else None


async def is_chat_disabled(chat_id: str) -> bool:
    status = await redis_client.get(chat_status_key(chat_id))
    return (
        status == ChatStatus.NOT_ENOUGH_PARTICIPANTS.value
        or status == ChatStatus.NOT_RELATED_TOPIC.value
    )


async def get_watchers(chat_id: str) -> list[str]:
    value = await redis_client.lrange(chat_watchers_key(chat_id), 0, -1)
    return [str(v) for v in value] if value else []
