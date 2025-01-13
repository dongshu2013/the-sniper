import asyncio
import json
import time

import asyncpg
from redis.asyncio import Redis

from src.config import (
    DATABASE_URL,
    REDIS_URL,
    SERVICE_PREFIX,
    chat_info_key,
    chat_messages_key,
)

HOURS_24 = 24 * 60 * 60  # 24 hours in seconds

redis = Redis.from_url(REDIS_URL)


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)
    try:
        current_time = int(time.time())
        cutoff_time = current_time - 3600 * 24

        query = """
            SELECT
                chat_id,
                COUNT(*) as messages_24h
            FROM chat_messages
            WHERE message_timestamp >= $1
            GROUP BY chat_id
            ORDER BY messages_24h DESC
        """
        results = await pg_conn.fetch(query, cutoff_time)

        chat_infos = {}
        for row in results:
            chat_id = row["chat_id"]
            chat_info = await redis.get(chat_info_key(chat_id))
            chat_infos[chat_id] = json.loads(chat_info)
            chat_infos[chat_id]["messages_24h"] = row["messages_24h"]
            pending_messages = await redis.llen(chat_messages_key(chat_id))
            chat_infos[chat_id]["pending_messages"] = pending_messages or 0

        sorted_results = sorted(
            chat_infos.values(), key=lambda x: x["pending_messages"], reverse=True
        )
        for result in sorted_results:
            print(
                f"{result['name']}: "
                f"pending_messages={result['pending_messages']}, "
                f"members={result['participants_count']}, "
                f"messages_24h={result['messages_24h']}"
            )

        info_pattern = f"{SERVICE_PREFIX}:chat:*:info"
        info_keys = await redis.keys(info_pattern)
        print(f"Total chat with info: {len(info_keys)}")
        print(f"Total chats with messages: {len(sorted_results)}")
    finally:
        await redis.aclose()  # Properly close Redis connection


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
