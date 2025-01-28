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


EVALUATION_WINDOW_SECONDS = 3600 * 72


class EntityExtractor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=EVALUATION_WINDOW_SECONDS)
        self.batch_size = 20
        self.pg_pool = None
        self.agent_client = AgentClient()
        self.queue = asyncio.Queue()
        self.workers = []

    async def prepare(self):
        self.pg_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=self.batch_size, max_size=self.batch_size
        )
        self.workers = [
            asyncio.create_task(self.evalute_chat_item())
            for _ in range(self.batch_size)
        ]
        logger.info(f"{self.__class__.__name__} processor initiated")

    async def process(self):
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, chat_id, name, username, about, participants_count,
                pinned_messages, initial_messages, admins, category, category_metadata,
                entity, entity_metadata, ai_about
                FROM chat_metadata
                WHERE category_metadata is null and evaluated_at < $1
                ORDER BY evaluated_at ASC
                """,
                int(time.time()) - EVALUATION_WINDOW_SECONDS,
            )
            if not rows:
                logger.info("no groups to process")
                return

            for row in rows:
                await self.queue.put(await self._to_chat_metadata(row, conn))
            logger.info(f"enqueueing {len(rows)} groups")

    async def evalute_chat_item(self):
        while True:
            chat_metadata = await self.queue.get()
            async with self.pg_pool.acquire() as conn:
                logger.info(
                    f"processing group: {chat_metadata.chat_id} - {chat_metadata.name}"
                )
                recent_messages = await self._get_latest_messages(chat_metadata, conn)
                context = await self._gather_context(
                    chat_metadata, recent_messages, conn
                )

                classification = await self._classify_chat(context, conn)
                logger.info(f"classification result: {classification}")
                parsed_classification = parse_ai_response(classification)
                if not parsed_classification:
                    logger.info("no classification found")
                    await conn.execute(
                        """
                            UPDATE chat_metadata
                            SET evaluated_at = $1
                            WHERE chat_id = $2
                            """,
                        int(time.time()),
                        chat_metadata.chat_id,
                    )
                    return

                logger.info(f"classification: {parsed_classification}")
                description = parsed_classification.get("description")
                category_data = parsed_classification.get("category", {})
                entity_data = parsed_classification.get("entity", {})

                if isinstance(category_data, dict):
                    category = category_data.get("data")
                    category_metadata = {
                        "ai_genereated": category_data.get("data"),
                        "confidence": category_data.get("confidence", 0),
                        "reason": category_data.get("reason", ""),
                    }
                else:
                    category = None
                    category_metadata = {
                        "ai_genereated": None,
                        "confidence": -1,
                        "reason": "Failed to evaluate category",
                    }
                old_category_metadata = chat_metadata.category_metadata
                if category_metadata.get("confidence") < old_category_metadata.get(
                    "confidence", 0
                ):
                    category = chat_metadata.category
                    category_metadata = old_category_metadata

                if isinstance(entity_data, dict):
                    entity = entity_data.get("data")
                    entity_metadata = {
                        "ai_genereated": entity_data.get("data"),
                        "confidence": entity_data.get("confidence", 0),
                        "reason": entity_data.get("reason", ""),
                    }
                else:
                    entity = None
                    entity_metadata = {
                        "ai_genereated": None,
                        "confidence": -1,
                        "reason": "Failed to evaluate entity",
                    }

                old_entity_metadata = chat_metadata.entity_metadata
                if entity_metadata.get("confidence") < old_entity_metadata.get(
                    "confidence", 0
                ):
                    entity = chat_metadata.entity
                    entity_metadata = old_entity_metadata

                update_query = """
                        UPDATE chat_metadata
                        SET category = $1,
                            category_metadata = $2,
                            entity = $3,
                            entity_metadata = $4,
                            ai_about = $5,
                            evaluated_at = $6
                        WHERE chat_id = $7
                    """
                await conn.execute(
                    update_query,
                    category,
                    json.dumps(category_metadata),
                    json.dumps(entity),
                    json.dumps(entity_metadata),
                    description,
                    int(time.time()),
                    chat_metadata.chat_id,
                )
                logger.info(
                    f"updated group: {chat_metadata.chat_id} - {chat_metadata.name}"
                )

    async def _to_chat_metadata(self, row: dict, conn) -> ChatMetadata:
        pinned_messages = json.loads(row["pinned_messages"] or "[]")
        initial_messages = json.loads(row["initial_messages"] or "[]")
        admins = json.loads(row["admins"] or "[]")

        message_ids = set()
        message_ids.update(pinned_messages)
        message_ids.update(initial_messages)

        message_rows = await conn.fetch(
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

        entity = json.loads(row["entity"] or "{}")
        category_metadata = json.loads(row["category_metadata"] or "{}")
        entity_metadata = json.loads(row["entity_metadata"] or "{}")
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
            category=row["category"],
            category_metadata=category_metadata,
            entity=entity,
            entity_metadata=entity_metadata,
            ai_about=row["ai_about"],
        )

    async def _get_latest_messages(
        self, chat_metadata: ChatMetadata, conn, limit: int = 10
    ) -> list[ChatMessage]:
        rows = await conn.fetch(
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
        self, chat_metadata: ChatMetadata, recent_messages: list[ChatMessage], conn
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

    async def _classify_chat(self, context: str, conn) -> str | None:
        response = await self.agent_client.chat_completion(
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
        return response


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
  * Has "verify", "tap to verify" or "human verification" button/link
  * Very few messages posted by the group owner, no user messages and no recent messages
  * If the group doesn't contain any human verification related messages, do not classify it as PORTAL_GROUP

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

2. DESCRIPTION:

- Write a concise introduction about the group based on the provided context.
- Keep the description between 100-200 characters
- Focus on:
  - Main purpose/topic of the group
  - Activity level and engagement
  - Key features or unique aspects
- Use natural, engaging language
- Include relevant facts from pinned messages or description
- Avoid speculation or unsupported claims
- If you cannot find any relevant information, return "No enough data to evaluate"

3. ENTITY DATA SCHEMA:

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


General Guidelines:
- For every category and entity, return the data, confidence of your evaluation, and reason for result and confidence
- If you don't have the enough data to evaluate entity, return null as the data, and 0 as the confidence, and reason as "No enough data to evaluate"
- If you don't have the enough data to evaluate category, return null as the data, return 0 as the confidence, and reason as "Not enough data to evaluate confidence"
- If you don't have the enough data to evaluate description, return "no_enough_data"

OUTPUT FORMAT:
{
    "category": {
        "data": "CATEGORY_NAME",
        "confidence": 0-100,
        "reason": "REASON_FOR_CONFIDENCE",
        },
    "description": "DESCRIPTION_OF_THE_GROUP",
    "entity": {
        "data": {entity_object_or_null},
        "confidence": 0-100,
        "reason": "REASON_FOR_CONFIDENCE",
    }
}
"""
# format: on


def main():
    processor = EntityExtractor()
    asyncio.run(processor.start_processing())


if __name__ == "__main__":
    main()
