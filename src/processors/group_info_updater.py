import json
import logging
import time
from typing import Optional, Tuple

from asyncpg import Connection
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import InputMessagesFilterPinned

from src.common.agent_client import AgentClient
from src.common.types import EntityType
from src.common.utils import normalize_chat_id, parse_ai_response
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Constants
MIN_MESSAGES_THRESHOLD = 10
INACTIVE_HOURS_THRESHOLD = 24
LOW_QUALITY_THRESHOLD = 3.0

MAX_QUALITY_REPORTS_COUNT = 5

# flake8: noqa: E501
# format: off
SYSTEM_PROMPT = """
You are an expert in memecoins and telegram groups. Now you joined a lot of group/channels. You goal is to
classify the group/channel into one of the following categories:
1. memecoin group: a group/channel that is about a specific memecoin
2. other group: a group/channel that is not about a memecoin
"""

ENTITY_EXTRACTOR_PROMPT = """
Given the following context extracted from a telegram chat, including title, description, pinned messages
and recent messages, extract the entity information.

Context:
{context}

Previous Extracted Entity:
{existing_entity}

Output the entity information in JSON format with following fields:
1. type: if the chat is about a specific memecoin, set to "memecoin", if it's not about a memecoin, set to "other", if you are not sure, set to "unknown".
2. name: if the chat is about a specific memecoin, set it to the ticker of the memecoin, otherwise set it to None
3. chain: if the chat is about a specific memecoin, set it to the chain of the memecoin, otherwise set it to None
4. address: if the chat is about a specific memecoin, set it to the address of the memecoin, otherwise set it to None
5. website: get the official website url of the group if there is any, otherwise set it to None
6. twitter: get the twitter username of the group if there is any, otherwise set it to None

Remember:
If the previous extracted entity is not None, you can use it as a reference to extract the entity information. You should
merge the new extracted entity with the previous extracted entity if it makes sense to you to get more comprehensive
information.
"""

QUALITY_EVALUATION_PROMPT = """
You are an expert in evaluating chat quality. Analyze the given messages and evaluate the chat quality.

You will follow the following evaluation guidelines:
1. User engagement and interactions: If there are a lot of different people posting and engaging, it's a good sign.
2. Conversation quality and diversity: If the messages are diverse and valuable, it's a good sign.

The group of users could be gathered for one topic(hiring, memecoin, events, project promotion, etc), the conversation
is considered as diverse as long as it's not the same group of people posting repetitive messages. The quality of the
conversation is considered as high quality if it's not repetitive and the information is relevant and valuable.


Output JSON format:
{
    "score": float (0-10),
    "reason": "very brief explanation"
}
For the reason field, you should explain why you give the score very briefly, the overall
reason should be less than 10 words if possible.

Scoring guidelines:
- 0: if the group is dead and no one is talking
- 1-3: few engagment, low quality and limited information (spam, repetitive posts, no real discussion)
- 4-6: medium quality (active engagement with some diverse information)
- 7-10: high quality (active engagement, diverse user interaction and valuable discussions)
"""

# format: on


class GroupInfoUpdater(ProcessorBase):
    def __init__(self, client: TelegramClient, pg_conn: Connection):
        super().__init__(interval=3 * 3600)
        self.client = client
        self.pg_conn = pg_conn
        self.ai_agent = AgentClient()

    async def process(self):
        dialogs = await self.get_all_dialogs()
        chat_ids = [normalize_chat_id(dialog.id) for dialog in dialogs]
        chat_info_map = await self.get_all_chat_metadata(chat_ids)
        logger.info(f"loaded {len(chat_info_map)} group metadata")

        for chat_id, dialog in zip(chat_ids, dialogs):
            if not dialog.is_group and not dialog.is_channel:
                continue

            chat_info = chat_info_map.get(chat_id, {})

            # 1. Get group description
            description = await self.get_group_description(dialog)
            logger.info(f"group description: {description}")

            # 2. Extract and update entity information
            entity, is_finalized = self._parse_entity(chat_info.get("entity", None))
            if not is_finalized:
                new_entity = await self._extract_and_update_entity(
                    dialog, entity, description
                )
                entity = entity.update(new_entity or {}) if entity else new_entity
                logger.info(f"extracted entity for group {dialog.name}: {entity}")

            # 3. Evaluate chat quality
            logger.info(f"evaluating chat quality for {chat_id}: {dialog.name}")
            quality_report = await self._evaluate_chat_quality(dialog)
            quality_reports = json.loads(chat_info.get("quality_reports", "[]"))
            if quality_report:
                quality_reports.append(quality_report)
            # only keep the latest 5 reports
            if len(quality_reports) > MAX_QUALITY_REPORTS_COUNT:
                quality_reports = quality_reports[-5:]

            logger.info(f"updating metadata for {chat_id}: {dialog.name}")
            await self._update_metadata(
                (
                    chat_id,
                    dialog.name or None,
                    description or None,
                    getattr(dialog.entity, "username", None),
                    getattr(dialog.entity, "participants_count", 0),
                    json.dumps(entity) if entity else None,
                    json.dumps(quality_reports),
                )
            )

    async def get_group_description(self, dialog: any) -> Optional[str]:
        if dialog.is_channel:
            result = await self.client(GetFullChannelRequest(channel=dialog.entity))
            return result.full_chat.about or None
        else:
            result = await self.client(GetFullChatRequest(chat_id=dialog.entity.id))
            return result.full_chat.about or None

    async def get_all_dialogs(self):
        dialogs = []
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            if not dialog.is_group and not dialog.is_channel:
                continue
            dialogs.append(dialog)
        return dialogs

    async def get_all_chat_metadata(self, chat_ids: list[str]) -> dict:
        rows = await self.pg_conn.fetch(
            "SELECT chat_id, entity, quality_reports FROM chat_metadata WHERE chat_id = ANY($1)",
            chat_ids,
        )
        return {
            row["chat_id"]: {
                "entity": row["entity"],
                "quality_reports": row["quality_reports"],
            }
            for row in rows
        }

    def _parse_entity(self, entity: dict | str | None) -> Tuple[dict | None, bool]:
        if entity is None:
            return None, False
        if isinstance(entity, str):
            try:
                entity = json.loads(entity)
            except Exception as e:
                logger.error(f"Failed to parse entity: {e}")
                return None, False
        entity_type = entity.get("type", None)
        if entity_type is None:
            return None, False
        if entity_type == EntityType.UNKNOWN.value:
            return None, False
        if entity_type == EntityType.MEMECOIN.value:
            # if entity is memecoin, it must have name and twitter
            is_finalized = entity.get("name") and entity.get("twitter")
            return entity, is_finalized
        return entity, True

    async def _gather_context(
        self, dialog: any, description: str | None
    ) -> Optional[str]:
        """Gather context from various sources in the chat."""
        context_parts = []
        context_parts.append(f"\nChat Title: {dialog.name}\n")
        if description:
            # Limit description length
            context_parts.append(f"\nDescription: {description[:500]}\n")

        try:
            pinned_messages = await self.client.get_messages(
                dialog.entity,
                filter=InputMessagesFilterPinned,
                limit=10,  # Reduced from 50 to 3 pinned messages
            )
            for message in pinned_messages:
                if message and message.text:
                    # Limit each pinned message length
                    context_parts.append(f"\nPinned Message: {message.text}\n")
        except Exception as e:
            logger.warning(f"Failed to get pinned messages: {e}")

        try:
            context_parts.append("\nRecent Messages:\n")
            messages = await self.client.get_messages(dialog.entity, limit=10)
            message_texts = [msg.text for msg in messages if msg and msg.text]
            context_parts.extend(message_texts)
        except Exception as e:
            logger.warning(f"Failed to get messages: {e}")

        # Join and limit total context length if needed
        context = "\n".join(filter(None, context_parts))
        return context[:24000]  # Limit total context length to be safe

    async def _extract_and_update_entity(
        self, dialog: any, existing_entity: dict | None, description: str | None
    ) -> Optional[dict]:
        """Extract entity information using AI."""
        try:
            context = await self._gather_context(dialog, description)
            response = await self.ai_agent.chat_completion(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": ENTITY_EXTRACTOR_PROMPT.format(
                            context=context,
                            existing_entity=(
                                json.dumps(existing_entity)
                                if existing_entity
                                else "No Data"
                            ),
                        ),
                    },
                ]
            )
            logger.info(f"response from ai: {response}")
            return parse_ai_response(
                response["choices"][0]["message"]["content"],
                ["type", "name", "chain", "address", "website", "twitter"],
            )
        except Exception as e:
            logger.error(
                f"Failed to extract entity for group {dialog.name}: {str(e)}",
                exc_info=True,
            )
            return None

    async def _evaluate_chat_quality(self, dialog: any) -> Optional[Tuple[float, str]]:
        """Evaluate chat quality based on recent messages."""
        try:
            messages = await self.client.get_messages(
                dialog.entity,
                limit=500,
                offset_date=int(time.time()) - INACTIVE_HOURS_THRESHOLD * 3600,
            )

            if len(messages) < MIN_MESSAGES_THRESHOLD:
                return 0.0, "inactive"

            # Prepare messages for quality analysis
            messages_text = "\n".join(
                [f"[{msg.date}] {msg.sender.username}: {msg.text}" for msg in messages]
            )
            messages_text = messages_text[:18000]  # limit buffer

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

    async def _update_metadata(self, update: tuple):
        """Update chat metadata."""
        try:
            (
                chat_id,
                name,
                about,
                username,
                participants_count,
                entity,
                quality_reports,
            ) = update
            await self.pg_conn.execute(
                """
                INSERT INTO chat_metadata (
                    chat_id, name, about, username, participants_count, entity, quality_reports, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP)
                ON CONFLICT (chat_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    about = EXCLUDED.about,
                    username = EXCLUDED.username,
                    participants_count = EXCLUDED.participants_count,
                    updated_at = CURRENT_TIMESTAMP,
                    entity = EXCLUDED.entity,
                    quality_reports = EXCLUDED.quality_reports
                """,
                chat_id,
                name,
                about,
                username,
                participants_count,
                entity,
                quality_reports,
            )
        except Exception as e:
            logger.error(f"Failed to update metadata: {e}")
