import asyncio
import json
import logging
import os
import time

from redis.asyncio import Redis
from telethon import TelegramClient, events

from src.config import SERVICE_PREFIX
from src.group_processor import ChatStatus, user_chat_key

from .bot_client import TelegramListener
from .config import PROCESSING_INTERVAL
from .group_processor import ChatProcessor

# Create logger instance
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


async def run():
    # Initialize bot
    logger.info("Initializing Telegram bot")
    listner = TelegramListener()
    logger.info("Starting Telegram bot")
    await listner.start()
    logger.info("Telegram bot started successfully")

    await register_handlers(listner.client, redis_client)
    grp_processor = ChatProcessor(listner.client, redis_client, PROCESSING_INTERVAL)

    try:
        await asyncio.gather(
            listner.client.run_until_disconnected(),
            grp_processor.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await grp_processor.stop_processing()
        await listner.stop()


async def register_handlers(client: TelegramClient, redis_client: Redis):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        if not event.is_group or not event.is_channel:
            return

        message_text = event.message.text
        if not message_text:
            return

        chat_id = str(event.chat_id)
        message_id = str(event.id)
        me = await client.get_me()
        should_process = await should_process_message(
            redis_client, chat_id, str(me.id), message_id
        )
        if not should_process:
            return

        pipelines = redis_client.pipeline()
        pipelines.set(message_seen_key(chat_id, message_id), int(time.time()))
        pipelines.lpush(
            f"{SERVICE_PREFIX}:chat:{chat_id}:messages",
            json.dumps(
                {
                    "sender": str(event.sender_id),
                    "message": message_text,
                    "timestamp": int(event.date.timestamp()),
                }
            ),
        )
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

    if status is None:
        return False

    status = json.loads(status)
    if status["status"] != ChatStatus.ACTIVE.value:
        return False

    return seen is None


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
