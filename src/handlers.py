import json
import logging
import time

from redis.asyncio import Redis
from telethon import TelegramClient, events

from src.config import SERVICE_PREFIX
from src.group_processor import ChatStatus, user_chat_key

logger = logging.getLogger(__name__)


async def register_handlers(client: TelegramClient, redis_client: Redis):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        """Handle incoming messages from groups"""
        logger.info(f"New message received: {event.message.text}")

        if not event.is_group or not event.is_channel:
            logger.info(
                f"New message received from non-group/channel: {event.message.text}"
            )
            return

        message_text = event.message.text
        if not message_text:
            logger.info(
                "Non text message received from "
                f"non-group/channel: {event.message.text}"
            )
            return

        chat_id = str(event.chat_id)
        message_id = str(event.id)
        me = await client.get_me()
        should_process = await should_process_message(
            redis_client, chat_id, str(me.id), message_id
        )
        if not should_process:
            logger.info(f"Message not processed: {event}")
            return

        logger.info(f"New group message received in {chat_id}: {message_text}")
        pipelines = redis_client.pipeline()
        pipelines.set(message_seen_key(chat_id, message_id), int(time.time()))
        pipelines.lpush(f"chat:{chat_id}:messages", message_text)
        await pipelines.execute()


def message_seen_key(chat_id: str, message_id: str):
    return f"{SERVICE_PREFIX}:message:{chat_id}:{message_id}:seen"


async def should_process_message(
    redis_client: Redis, chat_id: str, user_id: str, message_id: str
) -> bool:
    status, seen = await redis_client.mget(
        user_chat_key(user_id, chat_id),
        message_seen_key(chat_id, message_id),
    )

    status = json.loads(status)
    if status["status"] != ChatStatus.WATCHING.value:
        return False

    return seen is None
