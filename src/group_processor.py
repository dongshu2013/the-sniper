import asyncio
import json
import logging
from enum import Enum

from telethon import TelegramClient, types

from src.config import SERVICE_PREFIX, redis_client

logger = logging.getLogger(__name__)


MIN_PARTICIPANTS = 50
MIN_WATCHERS = 2


class DisableReason(Enum):
    NOT_ENOUGH_PARTICIPANTS = "not_enough_participants"
    NOT_RELATED_TOPIC = "not_related_topic"
    OTHER = "other"


class ChatProcessor:
    def __init__(self, client: TelegramClient, interval: int):
        self.interval = interval
        self.running = False
        self.client = client

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
            await try_watch_group_or_channel(
                self.client,
                dialog,
            )

    async def stop_processing(self):
        self.running = False


async def try_watch_group_or_channel(
    client: TelegramClient,
    dialog: types.Dialog,
):
    chat_id = str(dialog.id)
    # group is disabled
    if await is_group_or_channel_disabled(chat_id):
        return False

    watchers = await get_watchers(chat_id)

    # already watched
    me = await client.get_me()
    if me.id in watchers:
        return True

    # already watched by enough accounts
    if len(watchers) >= MIN_WATCHERS:
        return False

    if dialog.entity.participants_count >= MIN_PARTICIPANTS:
        logger.info(f"Watching group/channel: {dialog.name}")
        await watch_group_or_channel(dialog, me.id)
        return True
    else:
        logger.info(
            "Group/channel not enough participants: "
            f"{dialog.name} with {dialog.entity.participants_count} participants"
        )
        # we can have cron job to re-check disabled groups
        await disable_group_or_channel(chat_id, DisableReason.NOT_ENOUGH_PARTICIPANTS)
        return False


def chat_watchers_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:watchers"


def chat_info_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:info"


def chat_status_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:status"


def watcher_key(watcher: str, chat_id: str):
    return f"{SERVICE_PREFIX}:user:{watcher}:watch:{chat_id}"


async def watch_group_or_channel(dialog: types.Dialog, watcher: str):
    chat_id = str(dialog.id)
    pipeline = redis_client.pipeline()
    pipeline.lpush(chat_watchers_key(chat_id), watcher)
    pipeline.set(watcher_key(watcher, chat_id), "true")
    pipeline.set(
        chat_info_key(chat_id),
        json.dumps(
            {
                "name": dialog.name,
                "id": dialog.id,
                "participants_count": dialog.entity.participants_count,
            }
        ),
    )
    await pipeline.execute()


async def unwatch_group_or_channel(chat_id: str, watcher: str):
    pipeline = redis_client.pipeline()
    pipeline.lrem(chat_watchers_key(chat_id), 0, watcher)
    pipeline.delete(watcher_key(watcher, chat_id))
    await pipeline.execute()


async def disable_group_or_channel(chat_id: str, reason: DisableReason):
    watchers = await redis_client.lrange(chat_watchers_key(chat_id), 0, -1)
    pipeline = redis_client.pipeline()
    for watcher in watchers:
        pipeline.delete(watcher_key(watcher, chat_id))
    pipeline.delete(chat_watchers_key(chat_id))
    pipeline.set(chat_status_key(chat_id), reason.value)
    await pipeline.execute()


async def enable_group_or_channel(chat_id: str):
    await redis_client.delete(chat_status_key(chat_id))


async def is_group_or_channel_disabled(chat_id: str) -> bool:
    return await redis_client.get(chat_status_key(chat_id)) == "disabled"


async def get_watchers(chat_id: str) -> list[str]:
    value = await redis_client.lrange(chat_watchers_key(chat_id), 0, -1)
    return [str(v) for v in value] if value else []
