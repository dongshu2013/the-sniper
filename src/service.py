import time
from typing import Dict, List

import asyncpg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.common.config import DATABASE_URL

app = FastAPI()


async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)


@app.get("/tg_links", response_model=List[str])
async def get_tg_links():
    conn = await get_db_connection()
    try:
        query = """
            SELECT DISTINCT chat_id
            FROM tg_link_status
            WHERE status = 'pending'
            ORDER BY chat_id
        """
        results = await conn.fetch(query)
        return [str(result["chat_id"]) for result in results]
    finally:
        await conn.close()


@app.get("/stats", response_model=Dict)
async def get_stats():
    conn = await get_db_connection()
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
        results = await conn.fetch(query, cutoff_time)
        stats = {
            "chats": [
                {
                    "chat_id": str(result["chat_id"]),
                    "messages_24h": result["messages_24h"],
                }
                for result in results
            ],
            "total_chats": len(results),
        }
        return JSONResponse(content=stats)
    finally:
        await conn.close()
