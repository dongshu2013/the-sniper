import json
import logging
from typing import Optional

import asyncpg
from telethon import Message

from src.common.types import ChatMessage, ChatMessageButton

logger = logging.getLogger(__name__)


def to_chat_message(message: Message) -> ChatMessage | None:
    if not message.is_group or not message.is_channel:
        return None

    if not should_process(message):
        return None

    chat_id = str(message.chat_id)
    if chat_id.startswith("-100"):
        chat_id = chat_id[4:]

    message_id = str(message.id)

    reply_to = None
    topic_id = None
    if message.reply_to:
        if message.reply_to.forum_topic:
            if message.reply_to.reply_to_top_id:
                reply_to = message.reply_to.reply_to_msg_id
                topic_id = message.reply_to.reply_to_top_id
            else:
                topic_id = message.reply_to.reply_to_msg_id
        else:
            reply_to = message.reply_to.reply_to_msg_id

    message_buttons = []
    if message.buttons:
        message_buttons = [
            ChatMessageButton(
                text=getattr(button, "text", ""),
                url=getattr(button, "url", ""),
            )
            for button in message.buttons
        ]

    from_id = getattr(message, "from_id", {})
    sender_id = getattr(from_id, "user_id", None)
    return ChatMessage(
        message_id=message_id,
        chat_id=chat_id,
        message_text=message.text,
        sender_id=str(sender_id),
        message_timestamp=int(message.date.timestamp()),
        reply_to=str(reply_to) if reply_to else None,
        topic_id=str(topic_id) if topic_id else None,
        buttons=message_buttons,
    )


def should_process(message: Optional[Message]) -> bool:
    return message and (message.text or message.buttons)


async def store_messages(pg_conn: asyncpg.Connection, messages: list[ChatMessage]):
    if len(messages) == 0:
        return 0

    try:
        await pg_conn.executemany(
            """
            INSERT INTO chat_messages (
                message_id,
                chat_id,
                message_text,
                reply_to,
                topic_id,
                sender_id,
                message_timestamp,
                buttons
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (chat_id, message_id) DO NOTHING
            """,
            [
                (
                    m.message_id,
                    m.chat_id,
                    m.message_text,
                    m.reply_to,
                    m.topic_id,
                    m.sender_id,
                    m.message_timestamp,
                    json.dumps(m.buttons),
                )
                for m in messages
            ],
        )
        return len(messages)
    except Exception as e:
        logger.error(f"Database error: {e}")
        return 0
