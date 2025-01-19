import json
import logging
from typing import Optional, Tuple

from telethon import TelegramClient
from telethon.tl.types import InputMessagesFilterPinned

from src.common.agent_client import AgentClient
from src.common.types import EntityType
from src.common.utils import parse_ai_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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

# format: on


async def _gather_context(
    client: TelegramClient, dialog: any, description: str | None
) -> Optional[str]:
    """Gather context from various sources in the chat."""
    context_parts = []
    context_parts.append(f"\nChat Title: {dialog.name}\n")
    if description:
        # Limit description length
        context_parts.append(f"\nDescription: {description[:500]}\n")

    try:
        pinned_messages = await client.get_messages(
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
        messages = await client.get_messages(dialog.entity, limit=10)
        message_texts = [msg.text for msg in messages if msg and msg.text]
        context_parts.extend(message_texts)
    except Exception as e:
        logger.warning(f"Failed to get messages: {e}")

    # Join and limit total context length if needed
    context = "\n".join(filter(None, context_parts))
    return context[:24000]  # Limit total context length to be safe


async def extract_and_update_entity(
    client: TelegramClient,
    dialog: any,
    existing_entity: dict | None,
    description: str | None,
) -> Optional[dict]:
    """Extract entity information using AI."""
    try:
        ai_agent = AgentClient()
        context = await _gather_context(client, dialog, description)
        response = await ai_agent.chat_completion(
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


def parse_entity(entity: dict | str | None) -> Tuple[dict | None, bool]:
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
