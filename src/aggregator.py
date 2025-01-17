import asyncio
import logging

import asyncpg

from src.common.config import DATABASE_URL
from src.processors.tg_link_importer import TgLinkImporter

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)

    tg_link_importer = TgLinkImporter(pg_conn)

    try:
        await asyncio.gather(
            tg_link_importer.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
