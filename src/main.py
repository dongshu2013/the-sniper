import asyncio
import logging
import os

from redis.asyncio import Redis

from src.group_processor import ChatProcessor

from .bot_client import TelegramListener
from .config import PROCESSING_INTERVAL
from .handlers import register_handlers
from .message_processor import MessageProcessor

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
    msg_processor = MessageProcessor(PROCESSING_INTERVAL)
    grp_processor = ChatProcessor(listner.client, redis_client, PROCESSING_INTERVAL)

    try:
        await asyncio.gather(
            listner.client.run_until_disconnected(),
            msg_processor.start_processing(),
            grp_processor.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        # await processor.stop_processing()
        await listner.stop()


def main():
    asyncio.run(run())
