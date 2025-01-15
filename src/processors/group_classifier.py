import logging
from typing import Optional

from asyncpg import Connection as AsyncpgConnection
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


class GroupClassifier(ProcessorBase):
    def __init__(
        self, tg_client: TelegramClient, redis_client: Redis, pg_conn: AsyncpgConnection
    ):
        self.tg_client = tg_client
        self.redis_client = redis_client
        self.pg_conn = pg_conn
        self.ai_agent = AgentClient()

    async def process(self):
        for chat in self.tg_client.iter_dialogs():
            if not chat.is_group and not chat.is_channel:
                continue

            chat_id = str(chat.id)
            if chat_id.startswith("-100"):
                chat_id = chat_id[4:]

            entity_id = await self.redis_client.get(chat_entity_key(chat_id))
            if entity_id:  # already classified
                continue

            context = await self._gather_context(chat)
            if context:
                entity = await self._extract_entity(context)
                logger.info(f"Entity: {entity}")
                # if entity:
                #     entity_id = await self._search_entity(entity)
                #     if not entity_id:
                #         entity_id = await self.ai_agent.create_entity(entity)
                #     await self.redis_client.set(chat_entity_key(chat_id), entity_id)

    async def _gather_context(self, chat) -> str:
        """Gather context from various sources in the chat."""
        context_parts = []

        # Add chat title and description
        context_parts.append(f"Chat Title: {chat.title}")
        about = getattr(chat.entity, "about", None)
        if about:
            context_parts.append(f"Description: {about}")

        # Get all pinned messages
        try:
            pinned_messages = await self.client.get_messages(chat, filter="pinned")
            for pinned in pinned_messages:
                if pinned and pinned.text:
                    context_parts.append(f"Pinned Message: {pinned.text}")
        except Exception as e:
            logging.warning(f"Failed to get pinned messages: {e}")

        # Get recent messages
        try:
            messages = await self.client.get_messages(chat, limit=50)
            message_texts = [msg.text for msg in messages if msg and msg.text]
            context_parts.extend(message_texts)
        except Exception as e:
            logging.warning(f"Failed to get messages: {e}")

        return "\n".join(filter(None, context_parts))

    async def _extract_entity(self, context: str) -> Optional[str]:
        """Extract entity information from context."""
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

    async def _search_entity(self, entity: str) -> Optional[int]:
        """Search for entity in database."""
        return None


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
# format: on
