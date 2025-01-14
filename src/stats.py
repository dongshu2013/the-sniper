import asyncio
import time

import asyncpg

from src.common.config import DATABASE_URL


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
        sorted_results = sorted(results, key=lambda x: x["messages_24h"], reverse=True)
        for result in sorted_results:
            print(f"{result['chat_id']}: " f"messages_24h={result['messages_24h']}, ")
        print(f"Total chats with messages: {len(sorted_results)}")
    finally:
        await pg_conn.close()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
