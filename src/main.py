import asyncio
from logging import logger

from .bot_client import TelegramBot
from .config import PROCESSING_INTERVAL
from .handlers import register_handlers
from .message_processor import MessageProcessor


async def main():
    # Initialize bot
    bot = TelegramBot()
    await bot.start()

    # Register message handlers
    await register_handlers(bot.client)

    # Initialize and start message processor
    processor = MessageProcessor(PROCESSING_INTERVAL)

    try:
        # Run both the bot and processor
        await asyncio.gather(
            bot.client.run_until_disconnected(), processor.start_processing()
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await processor.stop_processing()
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
