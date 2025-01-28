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


EVALUATION_WINDOW_SECONDS = 3600 * 72  # 3 days


class EntityExtractor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=60)
        self.batch_size = 20
        self.pg_pool = None
        self.agent_client = AgentClient()
        self.processing_ids = set()
        self.queue = asyncio.Queue()
        self.workers = []

    async def prepare(self):
        self.pg_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=self.batch_size, max_size=self.batch_size
        )
        self.workers = [
            asyncio.create_task(self.evaluate_chat_item())
            for _ in range(self.batch_size)
        ]
        logger.info(f"{self.__class__.__name__} processor initiated")

    async def process(self):
        async with self.pg_pool.acquire() as conn:
            query = """
                SELECT id, chat_id, name, username, about, participants_count,
                pinned_messages, initial_messages, admins, category, category_metadata,
                entity, entity_metadata, ai_about, last_message_timestamp
                FROM chat_metadata
                """
            params = []

            if self.processing_ids:
                query += " AND chat_id != ALL($2)"
                params.append(list(self.processing_ids))

            query += " ORDER BY evaluated_at ASC"

            rows = await conn.fetch(query, *params)
            if not rows:
                logger.info("no groups to process")
                return

            logger.info(f"enqueueing {len(rows)} groups")
            for row in rows:
                if row["chat_id"] in self.processing_ids:
                    continue
                self.processing_ids.add(row["chat_id"])
                chat_metadata = await self._to_chat_metadata(row, conn)
                await self.queue.put(chat_metadata)
            logger.info(f"enqueued {len(rows)} groups")

    async def evaluate_chat_item(self):
        while self.running:
            chat_metadata: ChatMetadata = await self.queue.get()
            logger.info(
                f"processing group: {chat_metadata.name}, left {self.queue.qsize()} groups"
            )
            try:
                async with self.pg_pool.acquire() as conn:
                    recent_messages = await self._get_latest_messages(
                        chat_metadata, conn
                    )
                    last_message_timestamp = await self._get_last_message_timestamp(
                        chat_metadata, recent_messages
                    )
                    if not await self.should_evaluate(
                        chat_metadata, last_message_timestamp
                    ):
                        await self._record_skipping_evaluation(chat_metadata, conn)
                        raise Exception("skipping group")

                    context = await self._gather_context(
                        chat_metadata, recent_messages, conn
                    )
                    classification = await self._classify_chat(context, conn)
                    logger.info(f"classification result: {classification}")
                    parsed_classification = parse_ai_response(classification)
                    if not parsed_classification:
                        await self._record_skipping_evaluation(chat_metadata, conn)
                        raise Exception("no classification result")

                    logger.info(f"classification: {parsed_classification}")
                    description = parsed_classification.get("description")
                    category_data = parsed_classification.get("category", {})
                    entity_data = parsed_classification.get("entity", {})

                    (category, category_metadata) = self.update_field_metadata(
                        "category", category_data, chat_metadata
                    )
                    (entity, entity_metadata) = self.update_field_metadata(
                        "entity", entity_data, chat_metadata
                    )
                    update_query = """
                            UPDATE chat_metadata
                            SET category = $1,
                                category_metadata = $2,
                                entity = $3,
                                entity_metadata = $4,
                                ai_about = $5,
                                evaluated_at = $6,
                                last_message_timestamp = $7
                            WHERE chat_id = $8
                        """
                    logger.info(f"updating group: {chat_metadata.chat_id}")
                    await conn.execute(
                        update_query,
                        category,
                        json.dumps(category_metadata),
                        json.dumps(entity),
                        json.dumps(entity_metadata),
                        description,
                        int(time.time()),
                        last_message_timestamp,
                        chat_metadata.chat_id,
                    )
                    logger.info(
                        f"updated group: {chat_metadata.chat_id} - {chat_metadata.name}"
                    )
            except Exception as e:
                logger.error(f"error processing group: {chat_metadata.chat_id} - {e}")
            finally:
                self.processing_ids.remove(chat_metadata.chat_id)
                self.queue.task_done()

    async def should_evaluate(
        self, chat_metadata: ChatMetadata, last_message_timestamp: int
    ) -> bool:
        if (
            last_message_timestamp == 0
            or last_message_timestamp <= chat_metadata.last_message_timestamp
        ):
            logger.info(
                f"no new message in {chat_metadata.name}, "
                f"last message timestamp: {last_message_timestamp}"
            )
            return False

        chat_metadata.last_message_timestamp = last_message_timestamp
        category_metadata = chat_metadata.category_metadata
        # category is not evaluated
        if not category_metadata:
            return True

        # category is not confident
        if category_metadata.get("confidence", -1) < 50:
            return True

        # category is confident, only evaluate if it is KOL or CRYPTO_PROJECT
        if (
            chat_metadata.category == "KOL"
            or chat_metadata.category == "CRYPTO_PROJECT"
        ):
            entity_metadata = chat_metadata.entity_metadata
            if entity_metadata and entity_metadata.get("confidence", -1) < 50:
                return True

        logger.info(
            f"not kol or crypto project or entity data is already well covered:"
            f" {chat_metadata.chat_id} - {chat_metadata.name}"
        )
        return False

    async def _record_skipping_evaluation(self, chat_metadata: ChatMetadata, conn):
        await conn.execute(
            """
                UPDATE chat_metadata
                SET evaluated_at = $1,
                    last_message_timestamp = $2
                WHERE chat_id = $3
                """,
            int(time.time()),
            chat_metadata.last_message_timestamp,
            chat_metadata.chat_id,
        )

    def update_field_metadata(
        self, field_name: str, field_value: any, chat_metadata: ChatMetadata
    ):
        if isinstance(field_value, dict):
            field = field_value.get("data")
            field_metadata = {
                "ai_genereated": field_value.get("data"),
                "confidence": field_value.get("confidence", 0),
                "reason": field_value.get("reason", ""),
            }
        else:
            field = None
            field_metadata = {
                "ai_genereated": None,
                "confidence": -1,
                "reason": "Failed to evaluate",
            }

        # Use getattr instead of get() for accessing ChatMetadata attributes
        old_field_metadata = getattr(chat_metadata, field_name + "_metadata", {})
        if field_metadata.get("confidence") < old_field_metadata.get("confidence", 0):
            field = getattr(chat_metadata, field_name, None)
            field_metadata = old_field_metadata

        return (field, field_metadata)

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
            last_message_timestamp=row["last_message_timestamp"],
        )

    async def _get_latest_messages(
        self, chat_metadata: ChatMetadata, conn, limit: int = 50
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

    async def _get_last_message_timestamp(
        self, chat_metadata: ChatMetadata, recent_messages: list[ChatMessage]
    ) -> int:
        timestamps = []

        # Get timestamp from recent messages
        if recent_messages:
            timestamps.append(recent_messages[-1].message_timestamp)

        # Get timestamps from pinned messages
        if chat_metadata.pinned_messages:
            timestamps.extend(
                msg.message_timestamp for msg in chat_metadata.pinned_messages
            )

        # Get timestamps from initial messages
        if chat_metadata.initial_messages:
            timestamps.extend(
                msg.message_timestamp for msg in chat_metadata.initial_messages
            )

        # Return the most recent timestamp, or fallback to last_message_timestamp
        return max(timestamps) if timestamps else chat_metadata.last_message_timestamp

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
