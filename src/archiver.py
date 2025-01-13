import asyncio
import logging

from src.processors.message_processor import MessageProcessor

# Create logger instance
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run():
    msg_processor = MessageProcessor()
    try:
        await asyncio.gather(
            msg_processor.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await msg_processor.stop_processing()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
