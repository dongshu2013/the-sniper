import asyncio
import logging
import time
from asyncio import Queue
from datetime import datetime
from typing import List

import asyncpg

from src.common.config import DATABASE_URL
from src.common.utils import parse_ai_response
from src.helpers.message_helper import db_row_to_chat_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


MIN_MESSAGES_THRESHOLD = 10
INACTIVE_HOURS_THRESHOLD = 24
LOW_QUALITY_THRESHOLD = 5.0

MAX_QUALITY_REPORTS_COUNT = 5

QUALITY_SCORE_WEIGHT = 0.7
CATEGORY_ALIGNMENT_WEIGHT = 0.3

# flake8: noqa: E501
# format: off

QUALITY_EVALUATION_PROMPT = """You are an expert in evaluating Telegram group quality. Your task is to analyze messages and return a JSON object with quality metrics.

RESPONSE FORMAT:
You must respond with a valid JSON object containing exactly these fields:
{
    "score": <number between 0-10>,
    "category_alignment": <number between 0-10>
}

EVALUATION CRITERIA:

1. Quality Score (score):
- 0: Dead/inactive group
- 1-3: Low quality (spam/irrelevant)
- 4-6: Medium quality (some value)
- 7-9: High quality (consistent value)
- 10: Excellent (exceptional)

2. Category Alignment (category_alignment):
- 0: No relevance to category
- 1-3: Low alignment (mostly off-topic)
- 4-6: Medium alignment (mixed content)
- 7-9: High alignment (mostly relevant)
- 10: Perfect alignment

Consider these factors by group type:
- channel/megagroup: Focus on content quality and category alignment
- group/gigagroup: Evaluate both content and discussion quality

Evaluate based on category:
- PORTAL_GROUP: Verification process efficiency
- CRYPTO_PROJECT: Project updates and community engagement
- KOL: Content quality and expert insights
- VIRTUAL_CAPITAL: Investment discussions and networking
- EVENT: Event organization and information
- TECH_DISCUSSION: Technical depth and problem-solving
- FOUNDER: Startup discussions and mentorship
- OTHERS: General community value

Remember: Your response must be a single JSON object with exactly two numeric fields: "score" and "category_alignment".
"""

# format: on

BATCH_SIZE = 10
MAX_CONCURRENT_TASKS = 5

EVALUATION_INTERVAL_SECONDS = 3600 * 24  # 1 day


async def evaluate_chat_qualities(pg_conn, agent_client):
    """Evaluate chat quality for groups and update their quality scores."""

    # 1. Get chat metadata for evaluation
    rows = await pg_conn.fetch(
        """
        SELECT id, chat_id, category, name, type, evaluated_at
        FROM chat_metadata
        WHERE evaluated_at < $1
        ORDER BY evaluated_at DESC
        LIMIT 1000
        """,
        int(time.time()) - EVALUATION_INTERVAL_SECONDS,
    )

    if not rows:
        logger.info("No chats to evaluate")
        await asyncio.sleep(30)
        return

    task_queue = Queue()
    for row in rows:
        await task_queue.put(row)

    result_queue = Queue()

    tasks = []
    for _ in range(MAX_CONCURRENT_TASKS):
        task = asyncio.create_task(
            process_chat_worker(task_queue, result_queue, DATABASE_URL, agent_client)
        )
        tasks.append(task)

    update_task = asyncio.create_task(update_scores_worker(result_queue, DATABASE_URL))

    await task_queue.join()

    for task in tasks:
        task.cancel()

    await result_queue.join()
    update_task.cancel()

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
        await update_task
    except asyncio.CancelledError:
        pass


async def process_chat_worker(
    task_queue: Queue, result_queue: Queue, db_url: str, agent_client
):
    """Process the work task of evaluating a single chat"""
    pg_conn = await asyncpg.connect(db_url)
    try:
        while True:
            try:
                row = await task_queue.get()

                chat_id = row["chat_id"]
                category = row["category"]
                chat_type = row["type"]

                # Get messages for evaluation
                message_rows = await pg_conn.fetch(
                    """
                    SELECT chat_id, message_id, reply_to, topic_id,
                        sender_id, message_text, buttons, message_timestamp
                    FROM chat_messages
                    WHERE chat_id = $1
                    ORDER BY message_timestamp DESC
                    LIMIT 500
                    """,
                    chat_id,
                )

                if not message_rows or len(message_rows) < MIN_MESSAGES_THRESHOLD:
                    task_queue.task_done()
                    continue

                messages = [db_row_to_chat_message(msg_row) for msg_row in message_rows]

                # Prepare messages for AI evaluation
                messages.reverse()
                message_texts = []
                for msg in messages:
                    message_texts.append(
                        f"[{datetime.fromtimestamp(msg.message_timestamp).isoformat()}] "
                        f"User {msg.sender_id}: {msg.message_text}"
                    )

                messages_text = "\n".join(message_texts)[:16000]

                # Use AI to evaluate quality
                response = await agent_client.chat_completion(
                    messages=[
                        {"role": "system", "content": QUALITY_EVALUATION_PROMPT},
                        {
                            "role": "user",
                            "content": f"Evaluate this group:\nCategory: {category or 'OTHERS'}\nType: {chat_type}\n\nMessages:\n{messages_text}",
                        },
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    max_tokens=100,
                )

                if not response:
                    logger.error(f"No response from AI for chat {chat_id}")
                    task_queue.task_done()
                    continue

                result = parse_ai_response(response, ["score", "category_alignment"])
                if result:
                    quality_score = (
                        float(result["score"]) * QUALITY_SCORE_WEIGHT
                        + float(result["category_alignment"])
                        * CATEGORY_ALIGNMENT_WEIGHT
                    )
                    quality_score = round(quality_score, 2)
                    if quality_score > 0:
                        await result_queue.put((row["id"], quality_score))

                task_queue.task_done()

            except Exception as e:
                logger.error(f"Error processing chat {chat_id}: {e}", exc_info=True)
                task_queue.task_done()
    finally:
        await pg_conn.close()


async def update_scores_worker(result_queue: Queue, db_url: str):
    """Process the database update task"""
    pg_conn = await asyncpg.connect(db_url)
    try:
        batch: List[tuple] = []
        current_time = int(time.time())

        while True:
            try:
                chat_id, score = await result_queue.get()
                batch.append((chat_id, score, current_time))

                if len(batch) >= BATCH_SIZE or result_queue.empty():
                    if batch:
                        update_queries = [
                            f"({id}, {score}, {ts})" for id, score, ts in batch
                        ]
                        update_query = f"""
                            UPDATE chat_metadata AS cm
                            SET
                                quality_score = v.score,
                                evaluated_at = v.evaluated_at
                            FROM (VALUES {','.join(update_queries)}) AS v(id, score, evaluated_at)
                            WHERE cm.id = v.id
                        """

                        try:
                            await pg_conn.execute(update_query)
                            logger.info(
                                f"Updated quality scores for {len(batch)} chats"
                            )
                        except Exception as e:
                            logger.error(f"Failed to update quality scores: {e}")

                        batch = []

                result_queue.task_done()

            except Exception as e:
                logger.error(f"Error in update worker: {e}", exc_info=True)
                result_queue.task_done()
    finally:
        await pg_conn.close()
