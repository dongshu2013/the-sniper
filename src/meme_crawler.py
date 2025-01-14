import asyncio
import logging

import asyncpg

from src.common.config import DATABASE_URL
from src.processors.meme_crawler import MemeCrawler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)
    crawler = MemeCrawler(pg_conn)
    
    try:
        await crawler.start_processing()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await crawler.stop_processing()
    finally:
        await pg_conn.close()

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main() 