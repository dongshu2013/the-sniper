import asyncio
import logging

import asyncpg
from redis.asyncio import Redis

from src.common.config import DATABASE_URL, REDIS_URL
from src.processors.msg_queue_processor import MessageQueueProcessor
from src.processors.score_summarizer import ChatScoreSummarizer
from src.processors.tg_link_importer import TgLinkImporter

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)

    tg_link_importer = TgLinkImporter(pg_conn)
    msg_queue_processor = MessageQueueProcessor(redis_client, pg_conn)
    summarizer = ChatScoreSummarizer(pg_conn)

    try:
        await asyncio.gather(
            tg_link_importer.start_processing(),
            msg_queue_processor.start_processing(),
            summarizer.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
