import json
import logging
import time
from typing import Optional, Tuple

from src.common.types import ChatStatus
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


# flake8: noqa: E501
# format: off

QUALITY_EVALUATION_PROMPT = """
You are an expert in evaluating chat quality. Analyze the given messages and evaluate the chat quality.

You will follow the following evaluation guidelines:
1. User engagement and interactions: If there are a lot of different people posting and engaging, it's a good sign.
2. Conversation quality and diversity: If the messages are diverse and providing different information(including promotional information), it's a good sign.
3. If the messages are repetitive and the same group of people are posting, it's a bad sign.

Output JSON format:
{
    "score": float (0-10),
    "reason": "very brief explanation"
}
For the reason field, you should explain why you give the score very briefly, the overall
reason should be less than 10 words if possible.

Scoring guidelines:
- 0: if the group is dead and no one is talking
- 1-3(low quality): low user engagement, spam, repetitive posts, no real discussion
- 4-6(medium quality): medium user engagement, less repetitive posts with some diverse information
- 7-10(high quality): active user engagement, diverse user posts, very few repetitive posts
- 10(excellent quality): active user engagment, a lot of real discussions happening, diverse information being shared
"""

# format: on


async def evaluate_chat_quality(dialog: any, chat_info: dict) -> Optional[dict]:
    chat_id = normalize_chat_id(dialog.id)
    logger.info(f"evaluating chat quality for {chat_id}: {dialog.name}")
    quality_reports, should_evaluate = _should_evaluate(
        status, chat_info.get("quality_reports", "[]")
    )
    if should_evaluate:
        quality_reports = quality_reports or []
        new_report = await _evaluate_chat_quality(dialog)
        if new_report:
            quality_reports.append(new_report)
            # only keep the latest 5 reports
            if len(quality_reports) > MAX_QUALITY_REPORTS_COUNT:
                quality_reports = quality_reports[-MAX_QUALITY_REPORTS_COUNT:]
            if len(quality_reports) == MAX_QUALITY_REPORTS_COUNT:
                scores = [get_quality_score(report) for report in quality_reports]
                scores = [score for score in scores if score is not None]
                average_score = sum(scores) / len(scores)
                latest_score = get_quality_score(quality_reports[-1])
                status = (
                    ChatStatus.LOW_QUALITY.value
                    if average_score < LOW_QUALITY_THRESHOLD
                    and latest_score < LOW_QUALITY_THRESHOLD
                    else ChatStatus.ACTIVE.value
                )
    return quality_reports, status


async def _evaluate_chat_quality(self, dialog: any) -> Optional[dict]:
    """Evaluate chat quality based on recent messages."""
    try:
        messages = await self.client.get_messages(
            dialog.entity,
            limit=500,
            offset_date=int(time.time()) - INACTIVE_HOURS_THRESHOLD * 3600,
        )

        if len(messages) < MIN_MESSAGES_THRESHOLD:
            return {
                "score": 0.0,
                "reason": "inactive",
                "processed_at": int(time.time()),
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
                {"role": "user", "content": f"Messages:\n{messages_text}"},
            ]
        )

        logger.info(f"response from ai: {response}")
        report = parse_ai_response(
            response["choices"][0]["message"]["content"], ["score", "reason"]
        )
        report["processed_at"] = int(time.time())
        return report
    except Exception as e:
        logger.error(
            f"Failed to evaluate chat quality: {e}",
            exc_info=True,
        )
        return None


def _should_evaluate(
    status: str, quality_reports: str
) -> Tuple[Optional[list[dict]], bool]:
    if status == ChatStatus.BLOCKED.value or status == ChatStatus.LOW_QUALITY.value:
        return None, False

    try:
        quality_reports = json.loads(quality_reports)
        if not quality_reports:
            return [], True

        if status == ChatStatus.EVALUATING.value:
            return quality_reports, True
        elif status == ChatStatus.ACTIVE.value:
            latest_evaluation = quality_reports[-1]["processed_at"]
            should_evaluate = (
                int(latest_evaluation)
                < int(time.time()) - INACTIVE_HOURS_THRESHOLD * 3600
            )
            return quality_reports, should_evaluate
        else:
            logger.error(f"invalid chat status: {status}")
            return quality_reports, True
    except Exception as e:
        logger.error(f"Failed to parse quality reports: {e}")
        return [], True


def get_quality_score(report: dict | list) -> float:
    return 0.0 if isinstance(report, list) else report.get("score", 0.0)
