import asyncio
import logging
import time
from typing import Optional

import asyncpg

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL
from src.common.types import ChatMessage, ChatMetadata
from src.common.utils import parse_ai_response
from src.helpers.message_helper import db_row_to_chat_message, gen_message_content
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


BATCH_SIZE = 10
EVALUATION_WINDOW_SECONDS = 3600 * 24

# flake8: noqa: E501
# format: off

SYSTEM_PROMPT = """
You are a Web3 community manager analyzing Telegram groups. Your task is to classify groups based on their content and characteristics.
"""

CLASSIFY_PROMPT = """
CLASSIFICATION GUIDELINES:

1. Primary Type Categories & Key Indicators:

PORTAL_GROUP
- Primary indicators:
  * Bot verification messages present (e.g., Safeguard, Rose, Captcha)
  * Minimal organic messages
  * High frequency of invite links
  * Keywords: verify, enter, portal, gateway
  * Limited member interactions

CRYPTO_PROJECT
- Primary indicators:
  * Project-specific updates and announcements
  * Token price/trading discussions
  * Development updates
  * Community support/FAQs
  * Official team member presence
  * Keywords: tokenomics, whitepaper, roadmap

KOL
- Primary indicators:
  * Content centered around specific individual
  * Personal analysis/insights
  * Regular expert commentary
  * Direct KOL engagement
  * Exclusive content references

TRADING
- Primary indicators:
  * Technical analysis posts
  * Entry/exit signals
  * Price predictions
  * Trading strategy discussions
  * Multiple asset discussions
  * Keywords: TA, signal, entry, exit, SL, TP

VIRTUAL_CAPITAL
- Primary indicators:
  * Investment strategy discussions
  * Portfolio updates
  * Fund performance metrics
  * Professional investment terminology
  * Institutional perspective

DEALFLOW
- Primary indicators:
  * Project pitches
  * Investment round discussions
  * Due diligence requests
  * Term sheet mentions
  * Team/valuation analysis

EVENT
- Primary indicators:
  * Specific date/time/location details
  * Speaker announcements
  * Registration information
  * Event updates/coordination
  * Keywords: meetup, conference, hackathon

TECH_DISCUSSION
- Primary indicators:
  * Technical protocol discussions
  * Code sharing/reviews
  * Architecture debates
  * Development topics
  * Specific focus areas: DeFi, NFT, L2, VM, DePIN
  * Keywords: implementation, protocol, architecture

FOUNDER
- Primary indicators:
  * Startup discussions
  * Fundraising topics
  * Team building
  * Growth strategies
  * Founder-specific challenges

PROGRAM_COHORT
- Primary indicators:
  * Structured program elements
  * Cohort announcements
  * Mentor interactions
  * Program milestones
  * Keywords: accelerator, incubator, batch

NEWS
- Primary indicators:
  * Regular news updates
  * Market analysis
  * Industry developments
  * Multiple source sharing
  * Minimal discussion/more broadcasting

GENERAL_CRYPTO
- Primary indicators:
  * Broad industry discussions
  * Multiple topics covered
  * Community-driven discussions
  * No specific project focus
  * Wide-ranging crypto topics

OTHERS
- Default category when none above fit
- Document reasoning for classification as "OTHERS"

2. ENTITY DATA SCHEMA:

For CRYPTO_PROJECT:
{
    "ticker": "",
    "chain": "",
    "contract": "",
    "website": "",
    "name": "",
    "social": {
        "twitter": "",
        "other": []  # other links like gmgn.ai, dexscreener, e.t.c
    }
}

For KOL:
{
    "name": "",
    "username": "",
    "website": "",
    "social": {
        "twitter": "",
        "telegram": "",
        "linkedin": "",
        "other": []
    }
}

For VIRTUAL_CAPITAL:
{
    "name": "",
    "website": "",
    "social": {
        "twitter": "",
        "linkedin": ""
    }
}

For EVENT:
{
    "name": "",
    "datetime": "",
    "location": "",
    "website": "",
    "social": {
        "lu.ma": "",
        "eventbrite": "",
        "twitter": "",
        "other": []
    }
}

For PROGRAM_COHORT:
{
    "name": "",
    "organizer": "",
    "website": "",
    "social": {
        "twitter": "",
        "linkedin": ""
    }
}

For TECH DISCUSSION:
{
    "topic": "", # if there is a major topic, set it to the topic
}

For all others: null

OUTPUT FORMAT:
{
    "type": "CATEGORY_NAME",
    "entity": {entity_object_or_null},
    "confidence": "HIGH|MEDIUM|LOW",
}
"""
# format: on


class EntityExtractor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=1)
        self.batch_size = BATCH_SIZE
        self.pg_conn = None
        self.agent_client = AgentClient()

    async def process(self):
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        chat_metadata = await self._get_chat_metadata()
        if not chat_metadata:
            logger.info("no groups to process")
            await asyncio.sleep(30)
            return

        recent_messages = await self._get_latest_messages(chat_metadata)
        context = await self._gather_context(chat_metadata, recent_messages)
        classification = await self._classify_chat(context)
        parsed_classification = parse_ai_response(classification, [])
        if not parsed_classification:
            logger.info("no classification found")
            return

        logger.info(f"classification: {parsed_classification}")

        update_query = """
            UPDATE chat_metadata
            SET category = $1,
                entity = $2,
                evaluated_at = $3
            WHERE chat_id = $4
        """
        await self.pg_conn.execute(
            update_query,
            parsed_classification.get("type"),
            parsed_classification.get("entity"),
            int(time.time()),
            chat_metadata.chat_id,
        )

    async def _get_chat_metadata(self) -> ChatMetadata:
        select_query = """
            SELECT id, chat_id, name, about, pinned_messages, initial_messages, admins
            FROM chat_metadata
            WHERE evaluated_at < $1
            ORDER BY evaluated_at ASC
            LIMIT 1
        """
        rows = await self.pg_conn.fetch(
            select_query, int(time.time()) - EVALUATION_WINDOW_SECONDS
        )
        if not rows:
            logger.info("no groups to process")
            return

        message_ids = set()
        for row in rows:
            message_ids.update(row["pinned_messages"])
            message_ids.update(row["initial_messages"])
        rows = await self.pg_conn.fetch(
            """SELECT chat_id, message_id, reply_to, topic_id,
            sender_id, message_text, buttons, message_timestamp
            FROM chat_message WHERE id IN ($1)""",
            list(message_ids),
        )
        messages = {row["message_id"]: db_row_to_chat_message(row) for row in rows}
        return ChatMetadata(
            chat_id=row["chat_id"],
            name=row["name"],
            about=row["about"],
            pinned_messages=[
                messages[message_id]
                for message_id in row["pinned_messages"]
                if message_id in messages
            ],
            initial_messages=[
                messages[message_id]
                for message_id in row["initial_messages"]
                if message_id in messages
            ],
            admins=row["admins"],
        )

    async def _get_latest_messages(
        self, chat_metadata: ChatMetadata, limit: int = 10
    ) -> list[ChatMessage]:
        select_query = """
            SELECT chat_id, message_id, reply_to, topic_id,
            sender_id, message_text, buttons, message_timestamp
            FROM chat_message WHERE chat_id = $1
            ORDER BY message_timestamp DESC
            LIMIT $2
        """
        rows = await self.pg_conn.fetch(select_query, chat_metadata.chat_id, limit)
        return [db_row_to_chat_message(row) for row in rows].reverse()

    async def _gather_context(
        self, chat_metadata: ChatMetadata, recent_messages: list[ChatMessage]
    ) -> Optional[str]:
        """Gather context from various sources in the chat."""
        context_parts = []
        context_parts.append(f"\nChat Title: {chat_metadata.name}\n")
        if chat_metadata.about:
            context_parts.append(f"\nDescription: {chat_metadata.about[:500]}\n")

        context_parts.extend(
            [
                f"\nPinned Message: {gen_message_content(message)}"
                for message in chat_metadata.pinned_messages
            ]
        )

        context_parts.append("\n\nRecent Messages:\n")
        if len(recent_messages) < len(chat_metadata.initial_messages):
            context_parts.extend(
                [
                    gen_message_content(msg)
                    for msg in chat_metadata.initial_messages
                    if msg
                ]
            )
        else:
            context_parts.extend(
                [gen_message_content(msg) for msg in recent_messages if msg]
            )

        context = "\n".join(filter(None, context_parts))
        return context[:24000]  # Limit total context length to be safe

    async def _classify_chat(self, context: str) -> str:
        return await self.agent_client.chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"""
                    Here are the classification guidelines:

                    {CLASSIFY_PROMPT}

                    Please analyze this Telegram group:

                    {context}

                    Provide the classification in the specified JSON format.
                    """,
                },
            ],
            temperature=0.1,  # Lower temperature for more consistent results
            response_format={"type": "json_object"},  # Ensure JSON response
        )
