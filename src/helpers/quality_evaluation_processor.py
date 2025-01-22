import logging
import time
from typing import Optional

from src.common.utils import normalize_chat_id, parse_ai_response
from src.processors.group_processor import QUALITY_EVALUATION_PROMPT

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

QUALITY_EVALUATION_PROMPT = """
You are an expert in evaluating Telegram group quality. Analyze the given messages and evaluate the chat quality based on group category and messages.

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
1. User engagement: Active participation and meaningful interactions
2. Content quality: Information value and relevance to category
3. Community health: Spam levels, moderation, and discussion atmosphere

You must return a JSON object with exactly two fields:
{
    "score": float,           # Overall quality score (0-10)
    "category_alignment": float  # How well content matches the category (0-10)
}

Scoring Guidelines by Category:
- PORTAL_GROUP: Verification efficiency (8-10: smooth, 4-7: moderate, 0-3: poor)
- CRYPTO_PROJECT: Project updates & engagement (8-10: active, 4-7: moderate, 0-3: minimal)
- KOL: Content quality (8-10: valuable, 4-7: mixed, 0-3: poor)
- VIRTUAL_CAPITAL: Discussion quality (8-10: high-value, 4-7: moderate, 0-3: low)
- EVENT: Organization (8-10: well organized, 4-7: adequate, 0-3: poor)
- TECH_DISCUSSION: Technical depth (8-10: deep, 4-7: moderate, 0-3: superficial)
- FOUNDER: Startup value (8-10: valuable, 4-7: moderate, 0-3: low)
- OTHERS: Engagement (8-10: high, 4-7: moderate, 0-3: low)

General Quality Indicators:
0: Dead group
1-3: Low quality (spam, irrelevant)
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


async def evaluate_chat_quality(dialog: any, chat_info: dict) -> Optional[float]:
    chat_id = normalize_chat_id(dialog.id)
    logger.info(f"evaluating chat quality for {chat_id}: {dialog.name}")
    
    category = chat_info.get("category")
    new_report = await _evaluate_chat_quality(dialog, category)
    
    if new_report:
        # Calculate final quality score considering category alignment
        score = new_report["score"]
        category_alignment = new_report["category_alignment"]
        return score * QUALITY_SCORE_WEIGHT + category_alignment * CATEGORY_ALIGNMENT_WEIGHT
        
    return 0.0


async def _evaluate_chat_quality(self, dialog: any, category: str) -> Optional[dict]:
    """Evaluate chat quality based on recent messages and category."""
    try:
        messages = await self.client.get_messages(
            dialog.entity,
            limit=500,
            offset_date=int(time.time()) - INACTIVE_HOURS_THRESHOLD * 3600,
        )

        if len(messages) < MIN_MESSAGES_THRESHOLD:
            return {
                "score": 0.0,
                "category_alignment": 0.0,
            }

        # Prepare messages for quality analysis
        message_texts = []
        for msg in messages:
            if msg.text:
                sender = await msg.get_sender()
                sender_id = sender.id if sender else "Unknown"
                message_texts.append(f"[{msg.date}] {sender_id}: {msg.text}")

        messages_text = "\n".join(message_texts)[:16000]  # limit buffer

        # Use AI to evaluate quality
        response = await self.ai_agent.chat_completion(
            [
                {"role": "system", "content": QUALITY_EVALUATION_PROMPT},
                {
                    "role": "user", 
                    "content": f"Group Category: {category or 'OTHERS'}\n\nMessages:\n{messages_text}"
                },
            ]
        )

        logger.info(f"response from ai: {response}")
        report = parse_ai_response(
            response["choices"][0]["message"]["content"],
            ["score", "category_alignment"]
        )
        report["processed_at"] = int(time.time())
        return report
    except Exception as e:
        logger.error(
            f"Failed to evaluate chat quality: {e}",
            exc_info=True,
        )
        return None
