import logging
import time
from typing import Optional, Tuple

from asyncpg import Connection
from redis.asyncio import Redis
from telethon import TelegramClient

from src.common.agent_client import AgentClient
from src.common.config import chat_entity_key
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

Output the entity information in JSON format with following fields:
1. type: if the chat is about a specific memecoin, set to "memecoin", otherwise set to "other"
2. name: if the chat is about a specific memecoin, set it to the ticker of the memecoin, otherwise set it to None
3. chain: if the chat is about a specific memecoin, set it to the chain of the memecoin, otherwise set it to None
4. address: if the chat is about a specific memecoin, set it to the address of the memecoin, otherwise set it to None
5. website: get the official website url of the group if there is any, otherwise set it to None
6. twitter: get the twitter username of the group if there is any, otherwise set it to None
"""

QUALITY_EVALUATION_PROMPT = """
You are an expert in evaluating chat quality. Analyze the given messages and evaluate:
1. Message frequency and distribution
2. Conversation quality and diversity
3. User engagement and interaction
4. Information value and relevance

Output JSON format:
{
    "score": float (0-10),
    "reason": "brief explanation"
}

Scoring guidelines:
- 0-3: Low quality (spam, repetitive, no real discussion)
- 4-6: Medium quality (some engagement but limited depth)
- 7-10: High quality (active discussion, valuable information)
"""
# format: on

class GroupInfoUpdater(ProcessorBase):
    def __init__(
        self, client: TelegramClient, redis_client: Redis, pg_conn: Connection
    ):
        super().__init__(interval=300)
        self.client = client
        self.redis_client = redis_client
        self.pg_conn = pg_conn
        self.ai_agent = AgentClient()

    async def process(self):
        updates = []
        logger.debug("---Starting group info update process")
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            if not dialog.is_group and not dialog.is_channel:
                continue

            chat_id = str(dialog.id)
            if chat_id.startswith("-100"):
                chat_id = chat_id[4:]

            # 1. Update basic metadata
            metadata = (
                chat_id,
                dialog.name or None,
                getattr(dialog.entity, "about", None),
                getattr(dialog.entity, "username", None),
                getattr(dialog.entity, "participants_count", 0),
            )
            updates.append(metadata)

            # 2. Extract and update entity information
            entity_json = await self.redis_client.get(chat_entity_key(chat_id))
            if not entity_json:  # Not classified yet
                logger.info(f"Classifying group {chat_id}: {dialog.name}")
                context = await self._gather_context(dialog)
                if context:
                    entity = await self._extract_entity(context)
                    if entity:
                        logger.info(f"Update {chat_id}: {entity}")
                        await self._update_entity(chat_id, entity)

            # 3. Evaluate chat quality and update tags
            quality_info = await self._evaluate_chat_quality(chat_id)
            if quality_info:
                await self._update_chat_tags(chat_id, quality_info)

        # Batch update metadata
        logger.info(f"---Attempting to update metadata for {len(updates)} groups")
        if updates:
            await self._batch_update_metadata(updates)

    async def _gather_context(self, chat) -> Optional[str]:
        """Gather context from various sources in the chat."""
        context_parts = []
        
        context_parts.append(f"Chat Title: {chat.title}")
        about = getattr(chat.entity, "about", None)
        if about:
            context_parts.append(f"Description: {about}")

        try:
            pinned_messages = await self.client.get_messages(
                chat.entity, filter="pinned"
            )
            for pinned in pinned_messages:
                if pinned and pinned.text:
                    context_parts.append(f"Pinned Message: {pinned.text}")
        except Exception as e:
            logger.warning(f"Failed to get pinned messages: {e}")

        try:
            messages = await self.client.get_messages(chat.entity, limit=50)
            message_texts = [msg.text for msg in messages if msg and msg.text]
            context_parts.extend(message_texts)
        except Exception as e:
            logger.warning(f"Failed to get messages: {e}")

        return "\n".join(filter(None, context_parts))

    async def _extract_entity(self, context: str) -> Optional[str]:
        """Extract entity information using AI."""
        try:
            logger.info(f"Context: {context}")
            response = await self.ai_agent.chat_completion(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": ENTITY_EXTRACTOR_PROMPT.format(context=context),
                    },
                ]
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Failed to extract entity: {e}")
            return None

    async def _evaluate_chat_quality(self, chat_id: str) -> Optional[Tuple[float, str]]:
        """Evaluate chat quality based on recent messages."""
        try:
            # Get recent messages count and timestamps
            recent_messages = await self.pg_conn.fetch(
                """
                SELECT message_timestamp, message_text, sender_id 
                FROM chat_messages 
                WHERE chat_id = $1 
                AND message_timestamp > $2
                ORDER BY message_timestamp DESC
                """,
                chat_id,
                int(time.time()) - INACTIVE_HOURS_THRESHOLD * 3600
            )

            if len(recent_messages) < MIN_MESSAGES_THRESHOLD:
                return 0.0, "inactive"

            # Prepare messages for quality analysis
            messages_text = "\n".join([
                f"[{msg['message_timestamp']}] {msg['sender_id']}: {msg['message_text']}"
                for msg in recent_messages
            ])

            # Use AI to evaluate quality
            response = await self.ai_agent.chat_completion(
                [
                    {"role": "system", "content": QUALITY_EVALUATION_PROMPT},
                    {"role": "user", "content": f"Messages:\n{messages_text}"},
                ]
            )
            
            result = response["choices"][0]["message"]["content"]
            quality_score = float(result.get("score", 0))
            quality_tag = "low_quality" if quality_score < LOW_QUALITY_THRESHOLD else "active"
            
            return quality_score, quality_tag

        except Exception as e:
            logger.error(f"Failed to evaluate chat quality: {e}")
            return None

    async def _update_chat_tags(self, chat_id: str, quality_info: Tuple[float, str]):
        """Update chat tags based on quality evaluation."""
        quality_score, quality_tag = quality_info
        try:
            await self.pg_conn.execute(
                """
                UPDATE chat_metadata 
                SET tag = $2, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = $1
                """,
                chat_id,
                quality_tag
            )
        except Exception as e:
            logger.error(f"Failed to update chat tags: {e}")

    async def _batch_update_metadata(self, updates):
        """Batch update chat metadata."""
        try:
            await self.pg_conn.executemany(
                """
                INSERT INTO chat_metadata (
                    chat_id, name, about, username, participants_count, updated_at
                ) VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (chat_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    about = EXCLUDED.about,
                    username = EXCLUDED.username,
                    participants_count = EXCLUDED.participants_count,
                    updated_at = CURRENT_TIMESTAMP
                """,
                updates
            )
        except Exception as e:
            logger.error(f"Failed to batch update metadata: {e}")

    async def _update_entity(self, chat_id: str, entity_json: str):
        """Update entity information in database and Redis."""
        try:
            await self.pg_conn.execute(
                """
                UPDATE chat_metadata 
                SET entity = $2::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = $1
                """,
                chat_id,
                entity_json
            )
            await self.redis_client.set(chat_entity_key(chat_id), entity_json)
        except Exception as e:
            logger.error(f"Failed to update entity: {e}")
