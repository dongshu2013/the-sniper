import asyncio
import json
import os

from redis.asyncio import Redis

from src.config import SERVICE_PREFIX, chat_info_key

redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


async def run():
    try:
        msg_pattern = f"{SERVICE_PREFIX}:chat:*:messages"
        msg_keys = await redis.keys(msg_pattern)
        for msg_key in msg_keys:
            num_of_messages = await redis.llen(msg_key)
            chat_id = str(msg_key).split(":")[2]
            chat_info = await redis.get(chat_info_key(chat_id))
            if chat_info:
                chat_info = json.loads(chat_info)
                chat_info["num_of_messages"] = num_of_messages
                print(f"Info for {chat_id}: {chat_info}")
            else:
                print(f"No info for {chat_id}: messages={num_of_messages}")
    finally:
        await redis.close()  # Properly close Redis connection


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
