import asyncio
import logging

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient, events

from src.common.bot_client import TelegramListener
from src.common.config import (
    DATABASE_URL,
    MESSAGE_QUEUE_KEY,
    REDIS_URL,
    chat_per_hour_stats_key,
    message_seen_key,
)
from src.common.types import ChatMessage
from src.processors.group_info_updater import GroupInfoUpdater
from src.processors.tg_link_processor import TgLinkProcessor

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)
    listner = TelegramListener()
    await listner.start()
    logger.info("Telegram bot started successfully")
    #    await register_handlers(listner.client)

    tg_link_processor = TgLinkProcessor(listner.client, pg_conn)
    grp_info_updater = GroupInfoUpdater(listner.client, pg_conn)

    try:
        await asyncio.gather(
            listner.client.run_until_disconnected(),
            tg_link_processor.start_processing(),
            grp_info_updater.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await listner.stop()


async def register_handlers(client: TelegramClient):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        if not event.is_group or not event.is_channel:
            return

        chat_id = str(event.chat_id)
        if chat_id.startswith("-100"):
            chat_id = chat_id[4:]

        message_id = str(event.id)
        if await redis_client.exists(message_seen_key(chat_id, message_id)):
            return

        message_data = ChatMessage(
            message_id=message_id,
            chat_id=chat_id,
            message_text=event.message.text,
            sender_id=str(event.sender_id),
            message_timestamp=int(event.date.timestamp()),
        )
        pipeline = redis_client.pipeline()
        pipeline.incr(chat_per_hour_stats_key(chat_id, "messages_count"))
        pipeline.set(message_seen_key(chat_id, message_id), "true")
        pipeline.lpush(MESSAGE_QUEUE_KEY, message_data.model_dump_json())
        await pipeline.execute()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
