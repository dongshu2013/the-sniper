import asyncio
import logging

import asyncpg

from src.common.config import DATABASE_URL
from src.processors.score_summarizer import ChatScoreSummarizer

# Create logger instance
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)
    score_summarizer = ChatScoreSummarizer(pg_conn)
    try:
        await asyncio.gather(
            score_summarizer.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await score_summarizer.stop_processing()
    finally:
        await pg_conn.close()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
