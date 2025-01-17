import asyncio
import logging

from src.processors.msg_queue_processor import MessageQueueProcessor
from src.processors.tg_link_importer import TgLinkImporter

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run():

    tg_link_importer = TgLinkImporter()
    msg_queue_processor = MessageQueueProcessor()

    try:
        await asyncio.gather(
            tg_link_importer.start_processing(),
            msg_queue_processor.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
