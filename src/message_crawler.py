import asyncio
import logging
import time

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient, events

from src.common.bot_client import TelegramListener
from src.common.config import (
    DATABASE_URL,
    REDIS_URL,
    chat_per_hour_stats_key,
    message_seen_key,
)
from src.processors.group_importer import GroupImporter

# Create logger instance
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)


async def run():
    # Initialize bot
    listner = TelegramListener()
    await listner.start()
    logger.info("Telegram bot started successfully")

    pg_conn = await asyncpg.connect(DATABASE_URL)

    await register_handlers(listner.client, pg_conn)
    grp_importer = GroupImporter(listner.client, redis_client, pg_conn)

    try:
        await asyncio.gather(
            listner.client.run_until_disconnected(),
            grp_importer.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await listner.stop()


async def register_handlers(client: TelegramClient, pg_conn: asyncpg.Connection):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        if not event.is_group or not event.is_channel:
            return

        message_text = event.message.text
        if not message_text:
            return

        chat_id = str(event.chat_id)
        message_id = str(event.id)
        seen = await redis_client.get(message_seen_key(chat_id, message_id))
        if seen:
            return

        await pg_conn.execute(
            """
            INSERT INTO chat_messages
                (message_id, chat_id, message_text,
                    sender_id, message_timestamp)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (chat_id, message_id) DO NOTHING
            """,
            message_id,
            chat_id,
            message_text,
            str(event.sender_id),
            int(event.date.timestamp()),
        )
        pipelines = redis_client.pipeline()
        pipelines.set(message_seen_key(chat_id, message_id), int(time.time()))
        pipelines.incr(chat_per_hour_stats_key(chat_id, "num_of_messages"), 1)
        await pipelines.execute()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
