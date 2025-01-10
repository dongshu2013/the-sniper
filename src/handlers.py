import json
import logging
import os
from enum import Enum

from redis.asyncio import Redis
from telethon import TelegramClient, events, types

# Create Redis client
redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

MIN_PARTICIPANTS = 50

logger = logging.getLogger(__name__)

SERVICE_PREFIX = "the_sinper_bot"

MIN_WATCHERS = 2


class DisableReason(Enum):
    NOT_ENOUGH_PARTICIPANTS = "not_enough_participants"
    NOT_RELATED_TOPIC = "not_related_topic"
    OTHER = "other"


async def register_handlers(client: TelegramClient):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        """Handle incoming messages from groups"""
        if not event.is_group or event.is_channel:
            return

        if not await validate_group_or_channel(event):
            return

        chat_id = str(event.chat_id)
        message_id = str(event.id)
        if await has_seen_message(chat_id, message_id):
            return

        await seen_message(chat_id, message_id)
        message_text = event.message.text

        logger.info(f"New group message received in {chat_id}: {message_text}")

        # Add message to the group-specific Redis queue
        queue_key = f"chat:{chat_id}:messages"
        await redis_client.lpush(queue_key, message_text)


def chat_watchers_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:watchers"


def chat_info_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:info"


def chat_status_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:status"


def watcher_key(watcher: str, chat_id: str):
    return f"{SERVICE_PREFIX}:user:{watcher}:watch:{chat_id}"


def message_seen_key(chat_id: str, message_id: str):
    return f"{SERVICE_PREFIX}:message:{chat_id}:{message_id}:seen"


async def watch_group_or_channel(chat: types.Chat, watcher: str):
    chat_id = str(chat.id)
    pipeline = redis_client.pipeline()
    pipeline.set(chat_info_key(chat_id), json.dumps(chat.to_dict()))
    pipeline.lpush(chat_watchers_key(chat_id), watcher)
    pipeline.set(watcher_key(watcher, chat_id), "true")
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


async def get_num_of_watchers(chat_id: str) -> int:
    return await redis_client.llen(chat_watchers_key(chat_id))


async def is_watcher(watcher: str, chat_id: str) -> bool:
    return await redis_client.get(watcher_key(watcher, chat_id)) == "true"


async def validate_group_or_channel(chat: types.Chat, client: TelegramClient):
    chat_id = str(chat.id)

    # group is disabled
    if await is_group_or_channel_disabled(chat.id):
        return False

    # already watched
    if await is_watcher(client.get_me().id, chat_id):
        return True

    num_of_watchers = await get_num_of_watchers(chat_id)
    # already watched by enough accounts
    if num_of_watchers >= MIN_WATCHERS:
        return False

    # check if the group has enough participants
    piter = await client.iter_participants(entity=chat, limit=MIN_PARTICIPANTS)
    participants_count = 0
    async for _ in piter:
        participants_count += 1

    if participants_count >= MIN_PARTICIPANTS:
        await watch_group_or_channel(chat_id, client.get_me().id)
        return True
    else:
        # we can have cron job to re-check disabled groups
        await disable_group_or_channel(chat_id, DisableReason.NOT_ENOUGH_PARTICIPANTS)
        return False


async def seen_message(chat_id: str, message_id: str):
    await redis_client.set(message_seen_key(chat_id, message_id), "seen")


async def has_seen_message(chat_id: str, message_id: str) -> bool:
    return await redis_client.get(message_seen_key(chat_id, message_id)) == "seen"


async def scan_group_participants(event: events.ChatAction):
    chat = await event.get_chat()
    chat_id = str(chat.id)

    participants = await event.client.get_participants(chat)

    # Create a pipeline for batch Redis operations
    pipe = redis_client.pipeline()

    # Create set key for all members in this chat
    members_set_key = f"{SERVICE_PREFIX}:chat:{chat_id}:member_ids"
    pipe.delete(members_set_key)  # Clear existing set

    for user in participants:
        # Add member ID to the set of all chat members
        pipe.sadd(members_set_key, user.id)

        # Store individual member details
        member_key = f"{SERVICE_PREFIX}:chat:{chat_id}:member:{user.id}"
        member_info = {
            "id": user.id,
            "username": user.username,
            "bot": user.bot,
            "is_admin": isinstance(user.participant, types.ChannelParticipantAdmin),
        }
        pipe.set(member_key, json.dumps(member_info))

    # Execute all Redis commands in pipeline
    await pipe.execute()
