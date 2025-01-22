import asyncio
from datetime import datetime
import logging
import time
from typing import Dict

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

QUALITY_EVALUATION_INTERVAL_SECONDS = 3600 * 24

# flake8: noqa: E501
# format: off

QUALITY_EVALUATION_PROMPT = """
You are an expert in evaluating Telegram group quality. Analyze the given messages and evaluate the chat quality based on group category, type and messages.

Group Types and Evaluation Focus:
- channel/megagroup: Focus on content quality and category alignment only (ignore discussion metrics)
- group/gigagroup: Evaluate both content and discussion quality

Group Category Guidelines:
- PORTAL_GROUP: Evaluate based on verification process efficiency and user flow
- CRYPTO_PROJECT: Focus on project updates, community engagement, and technical discussions
- KOL: Evaluate content quality, expert insights, and community interaction
- VIRTUAL_CAPITAL: Look for investment discussions, deal flow, and professional networking
- EVENT: Check event organization, participant engagement, and information sharing
- TECH_DISCUSSION: Assess technical depth, problem-solving, and knowledge sharing
- FOUNDER: Evaluate startup discussions, mentorship quality, and networking value
- OTHERS: General community engagement and value delivery

Evaluation Guidelines:
1. Content quality: Information value and relevance to category
2. Category alignment: How well the content matches the declared category
3. Community health (for groups only): User engagement, spam levels, and discussion atmosphere

You must return a JSON object with exactly two fields:
{
    "score": float,           # Overall quality score (0-10)
    "category_alignment": float  # How well content matches the category (0-10)
}

Scoring Guidelines by Category:
- PORTAL_GROUP: Content/verification quality (8-10: excellent, 4-7: moderate, 0-3: poor)
- CRYPTO_PROJECT: Updates & information (8-10: high-value, 4-7: moderate, 0-3: minimal)
- KOL: Content quality (8-10: valuable, 4-7: mixed, 0-3: poor)
- VIRTUAL_CAPITAL: Information quality (8-10: high-value, 4-7: moderate, 0-3: low)
- EVENT: Organization & info (8-10: well organized, 4-7: adequate, 0-3: poor)
- TECH_DISCUSSION: Technical content (8-10: deep, 4-7: moderate, 0-3: superficial)
- FOUNDER: Value & insights (8-10: valuable, 4-7: moderate, 0-3: low)
- OTHERS: Content value (8-10: high, 4-7: moderate, 0-3: low)

General Quality Indicators:
0: Dead/inactive
1-3: Low quality (irrelevant/spam)
4-6: Medium quality (some value)
7-9: High quality (consistent value)
10: Excellent (exceptional)

Category Alignment Indicators:
0: No relevance to category
1-3: Low alignment (mostly off-topic)
4-6: Medium alignment (mixed content)
7-9: High alignment (mostly relevant)
10: Perfect alignment (fully relevant)
"""

# format: on

async def evaluate_chat_qualities(pg_conn, agent_client):
    """Evaluate chat quality for groups and update their quality scores."""
    current_time = int(time.time())
    one_day_ago = current_time - QUALITY_EVALUATION_INTERVAL_SECONDS
    
    # 1. Get chat metadata for evaluation
    rows = await pg_conn.fetch(
        """
        SELECT id, chat_id, category, name, type
        FROM chat_metadata 
        WHERE evaluated_at < $1 
        ORDER BY evaluated_at DESC
        LIMIT 1000
        """,
        one_day_ago
    )
    
    if not rows:
        logger.info("No chats to evaluate")
        await asyncio.sleep(30)
        return

    quality_scores = {}
    
    for row in rows:
        try:
            chat_id = row['chat_id']
            category = row['category']
            chat_type = row['type']
            
            # 2. Get recent messages for the chat
            message_rows = await pg_conn.fetch(
                """
                SELECT chat_id, message_id, reply_to, topic_id,
                    sender_id, message_text, buttons, message_timestamp
                FROM chat_messages
                WHERE chat_id = $1
                AND message_timestamp > $2
                ORDER BY message_timestamp DESC
                LIMIT 500
                """,
                chat_id,
                one_day_ago
            )
            
            if not message_rows:
                continue

            messages = [db_row_to_chat_message(msg_row) for msg_row in message_rows]
            
            if len(messages) < MIN_MESSAGES_THRESHOLD:
                continue
                
            # 3. Prepare messages for AI evaluation
            messages.reverse()  # Only reverse once to get chronological order
            message_texts = []
            for msg in messages:
                message_texts.append(
                    f"[{datetime.fromtimestamp(msg.message_timestamp).isoformat()}] "
                    f"User {msg.sender_id}: {msg.message_text}"
                )
            
            messages_text = "\n".join(message_texts)[:16000]  # Limit buffer size
            
            # Use AI to evaluate quality
            response = await agent_client.chat_completion(
                messages=[
                    {"role": "system", "content": QUALITY_EVALUATION_PROMPT},
                    {
                        "role": "user",
                        "content": f"Group Category: {category or 'OTHERS'}\nGroup Type: {chat_type}\n\nMessages:\n{messages_text}"
                    }
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = parse_ai_response(response, ["score", "category_alignment"])
            if result:
                quality_score = (
                    float(result["score"]) * QUALITY_SCORE_WEIGHT +
                    float(result["category_alignment"]) * CATEGORY_ALIGNMENT_WEIGHT
                )
                quality_score = round(quality_score, 2)
                if quality_score > 0:
                    quality_scores[row['id']] = quality_score
            else:
                logger.error(f"Failed to parse AI response for chat {chat_id}")
                
        except Exception as e:
            logger.error(f"Failed to evaluate chat {chat_id}: {str(e)}", exc_info=True)
            
    # 4. Bulk update quality scores
    if quality_scores:
        await update_chat_qualities(pg_conn, quality_scores)
        logger.info(f"Successfully updated quality scores for {len(quality_scores)} chats")
    else:
        logger.info("No quality scores to update")


async def update_chat_qualities(pg_conn, quality_scores: Dict[int, float]) -> None:
    """Update quality scores for multiple chats in the database."""
    if not quality_scores:
        return
        
    current_time = int(time.time())
    update_queries = []
    for chat_id, score in quality_scores.items():
        update_queries.append(
            f"({chat_id}, {score}, {current_time})"
        )
        
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
        logger.info(f"Updated quality scores for {len(quality_scores)} chats")
    except Exception as e:
        logger.error(f"Failed to update quality scores: {e}")       
