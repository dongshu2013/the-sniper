import asyncio
import logging
import os

from redis.asyncio import Redis

# Create logger instance
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


async def run():
    pass


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
