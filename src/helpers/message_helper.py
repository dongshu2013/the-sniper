import json
import logging
from typing import Optional

import asyncpg
from telethon.tl.types import Message

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

    # Convert buttons to a serializable format
    buttons = []
    for row in message.buttons or []:
        for button in row:
            buttons.append(
                ChatMessageButton(
                    text=button.text,
                    url=button.url if hasattr(button, "url") else None,
                    data=(
                        button.data.decode("utf-8")
                        if hasattr(button, "data") and button.data
                        else None
                    ),
                )
            )

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
        buttons=buttons,
    )


def should_process(message: Optional[Message]) -> bool:
    return message and (
        message.text
        or message.buttons
        or (hasattr(message, "reply_markup") and message.reply_markup)
    )


async def store_messages(
    pg_conn: asyncpg.Connection, messages: list[Optional[ChatMessage]]
):
    if len(messages) == 0:
        return 0

    messages = [m for m in messages if m is not None]

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
                    json.dumps([b.model_dump() for b in m.buttons]),
                )
                for m in messages
            ],
        )
        return len(messages)
    except Exception as e:
        logger.error(f"Database error: {e}")
        return 0


def gen_message_content(message: ChatMessage) -> str:
    text = message.text
    for button in message.buttons:
        text += f"\nButton: {button.text} {button.url} {button.data}"
    return text


async def get_messages(
    pg_conn: asyncpg.Connection, chat_id: str, message_ids: list[str]
) -> dict[str, ChatMessage]:
    rows = await pg_conn.fetch(
        """
        SELECT chat_id, message_id, reply_to, topic_id,
        sender_id, message_text, buttons, message_timestamp
        FROM chat_message
        WHERE chat_id = $1 AND message_id IN ($2)
        """,
        chat_id,
        message_ids,
    )
    return {row["message_id"]: to_chat_message(row) for row in rows}


def db_row_to_chat_message(row: dict) -> ChatMessage | None:
    buttons = [
        ChatMessageButton(
            text=button["text"],
            url=button["url"],
            data=button["data"],
        )
        for button in json.loads(row["buttons"])
    ]
    return ChatMessage(
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        reply_to=row["reply_to"],
        topic_id=row["topic_id"],
        sender_id=row["sender_id"],
        message_text=row["message_text"],
        buttons=buttons,
        message_timestamp=row["message_timestamp"],
    )
