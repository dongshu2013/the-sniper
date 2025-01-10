import logging

from telethon import TelegramClient, events

from src.config import SERVICE_PREFIX, redis_client
from src.group_processor import is_watcher

logger = logging.getLogger(__name__)


async def register_handlers(client: TelegramClient):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        """Handle incoming messages from groups"""
        logger.info(f"New message received: {event.message.text}")

        if not event.is_group or not event.is_channel:
            logger.info(
                f"New message received from non-group/channel: {event.message.text}"
            )
            return

        me = await client.get_me()
        if not await is_watcher(me.id, event.chat.id):
            logger.info(f"Group/channel not validated: {event.chat.title}")
            return

        chat_id = str(event.chat_id)
        message_id = str(event.id)
        if await has_seen_message(chat_id, message_id):
            logger.info(f"Message already seen: {event}")
            return
        await seen_message(chat_id, message_id)

        message_text = event.message.text
        if not message_text:
            logger.info(
                "Non text message received from "
                f"non-group/channel: {event.message.text}"
            )
            return

        logger.info(f"New group message received in {chat_id}: {message_text}")
        # Add message to the group-specific Redis queue
        queue_key = f"chat:{chat_id}:messages"
        await redis_client.lpush(queue_key, message_text)


def message_seen_key(chat_id: str, message_id: str):
    return f"{SERVICE_PREFIX}:message:{chat_id}:{message_id}:seen"


async def seen_message(chat_id: str, message_id: str):
    await redis_client.set(message_seen_key(chat_id, message_id), "seen")


async def has_seen_message(chat_id: str, message_id: str) -> bool:
    return await redis_client.get(message_seen_key(chat_id, message_id)) == "seen"
