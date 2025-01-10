import asyncio
import logging

from .bot_client import TelegramListener
from .config import PROCESSING_INTERVAL
from .handlers import register_handlers
from .message_processor import MessageProcessor

# Create logger instance
logger = logging.getLogger(__name__)


async def run():
    # Initialize bot
    logger.info("Initializing Telegram bot")
    listner = TelegramListener()
    logger.info("Starting Telegram bot")
    await listner.start()
    logger.info("Telegram bot started successfully")

    # Register message handlers
    await register_handlers(listner.client)

    # Initialize and start message processor
    processor = MessageProcessor(PROCESSING_INTERVAL)

    try:
        # Run both the bot and processor
        await asyncio.gather(
            listner.client.run_until_disconnected(), processor.start_processing()
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await processor.stop_processing()
        await listner.stop()


def main():
    asyncio.run(run())
