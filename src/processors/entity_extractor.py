import asyncio
import json
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
  * Group name typically contains "Portal"
  * Contains bot verification messages (Safeguard, Rose, Captcha)
  * Has "verify" or "human verification" button/link
  * Only few messages posted by the group owner, no user messages

CRYPTO_PROJECT
- Primary indicators:
  * Smart contract address in description/pinned (e.g., 0x... or Ewdqjj...)
  * Group name often includes token ticker with $ (e.g., $BOX)
  * Project details in pinned messages/description
  * Keywords: tokenomics, whitepaper, roadmap

KOL (Key Opinion Leader)
- Primary indicators:
  * Group name/description features specific individual
  * KOL's username and introduction in description
  * Keywords: exclusive content, signals, alpha

VIRTUAL_CAPITAL
- Primary indicators:
  * Contains "VC" or "Venture Capital" in name/description
  * Keywords: investment strategy, portfolio, institutional

EVENT
- Primary indicators:
  * Group name includes event name/date
  * Contains event registration links (lu.ma, etc.)
  * Keywords: meetup, conference, hackathon, RSVP

TECH_DISCUSSION
- Primary indicators:
  * Group name/description mentions technical focus
  * Contains code discussions/snippets
  * Keywords: dev, protocol, smart contract, architecture

FOUNDER
- Primary indicators:
  * Group name contains "founder" or "startup"
  * Founder-focused discussions in description
  * Keywords: fundraising, startup, founder

OTHERS
- Use when no other category fits clearly
- Note specific reason for classification

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

For all others: null

OUTPUT FORMAT:
{
    "category": "CATEGORY_NAME",
    "entity": {entity_object_or_null},
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

        logger.info(f"processing group: {chat_metadata.chat_id} - {chat_metadata.name}")
        recent_messages = await self._get_latest_messages(chat_metadata)
        context = await self._gather_context(chat_metadata, recent_messages)

        classification = await self._classify_chat(context)
        parsed_classification = parse_ai_response(classification, [])
        if not parsed_classification:
            logger.info("no classification found")
            return

        category = parsed_classification.get("category")
        entity = parsed_classification.get("entity")
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
            category,
            json.dumps(entity),
            int(time.time()),
            chat_metadata.chat_id,
        )

    async def _get_chat_metadata(self) -> ChatMetadata:
        row = await self.pg_conn.fetchrow(
            """
            SELECT id, chat_id, name, username, about, participants_count,
            pinned_messages, initial_messages, admins
            FROM chat_metadata
            WHERE evaluated_at < $1
            ORDER BY evaluated_at ASC
            LIMIT 1
            """,
            int(time.time()) - EVALUATION_WINDOW_SECONDS,
        )
        if not row:
            logger.info("no groups to process")
            return

        pinned_messages = json.loads(row["pinned_messages"] or "[]")
        initial_messages = json.loads(row["initial_messages"] or "[]")
        admins = json.loads(row["admins"] or "[]")

        message_ids = set()
        message_ids.update(pinned_messages)
        message_ids.update(initial_messages)

        message_rows = await self.pg_conn.fetch(
            """
            SELECT chat_id, message_id, reply_to, topic_id,
            sender_id, message_text, buttons, message_timestamp
            FROM chat_messages
            WHERE chat_id = $1 AND message_id = ANY($2)
            """,
            row["chat_id"],
            list(message_ids),
        )
        messages = {
            msg_row["message_id"]: db_row_to_chat_message(msg_row)
            for msg_row in message_rows
        }
        return ChatMetadata(
            chat_id=row["chat_id"],
            name=row["name"],
            username=row["username"],
            about=row["about"],
            participants_count=row["participants_count"],
            pinned_messages=[
                messages[message_id]
                for message_id in pinned_messages
                if message_id in messages
            ],
            initial_messages=[
                messages[message_id]
                for message_id in initial_messages
                if message_id in messages
            ],
            admins=admins,
        )

    async def _get_latest_messages(
        self, chat_metadata: ChatMetadata, limit: int = 10
    ) -> list[ChatMessage]:
        rows = await self.pg_conn.fetch(
            """
            SELECT chat_id, message_id, reply_to, topic_id,
            sender_id, message_text, buttons, message_timestamp
            FROM chat_messages
            WHERE chat_id = $1
            ORDER BY message_timestamp DESC
            LIMIT $2
            """,
            chat_metadata.chat_id,
            limit,
        )
        if not rows:
            return []

        messages = [db_row_to_chat_message(row) for row in rows]
        messages.reverse()
        return messages

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

        context_parts.extend([f"\nTotal Members: {chat_metadata.participants_count}"])

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
