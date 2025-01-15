import json
import logging
import time
from asyncio.log import logger
from datetime import datetime

import asyncpg

from src.common.agent_client import AgentClient
from src.common.utils import parse_ai_response
from src.processors.processor import ProcessorBase

# flake8: noqa
# format off
SYSTEM_PROMPT = """
You are a Web3 expert who are minitoring chat groups of a lot of web3 project.
You goal is to analyze the messages and evaluate the quality of the
chat group and give it a score from 0 to 10. 0 means the chat group is not good for
the community and 10 means the project is very good for the community.


Instructions:
- You will be given a list of messages from a chat group. It could be any language.
  The sender is anonymized by a random number. The timestamp is in ISO format.
- You will need to give a score from 0 to 10. 0 means the project is not good for
  the community and 10 means the project is very good for the community.

Follow the following rules to evaluate the quality of the chat group:
- If no one is talking in the chat group, give it a low score.
- If a lot of people are talking in the chat group, give it a high score.
- If only a few people are talking in the chat group, check the quality of
  the messages. If they are repetitive messages, give it a low score. If the
  messages deliver diverse information, such as news, product updates,
  partnerships etc., you can give it a mid score.

Remember:
- You will need to give a short summary of what happened in the chat group and why you give the score.
- Be concise and short for the summary, few sentences should be sufficient, do not write a lot of text.

Output Instructions:
- You will need to output and only output a JSON object with the following fields:
  - score: The score of the chat group from 0 to 10.
  - summary: A short summary of what happened in the chat group and why you give the score.
  - highlights: select some highlights from from the chat messages such as high-quality discussions,
    events, product updates and partnership updates. Combine all highlights into a single string and
    separate each highlight by a comma. You don't need to include the user information in the highlight,
    only share what happened to the project briefly.
"""
# format on

MIN_MESSAGES_TO_PROCESS = 10

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


MIN_SUMMARY_INTERVAL = 3600 * 6  # every 6 hours


class ChatScoreSummarizer(ProcessorBase):
    def __init__(self, pg_conn: asyncpg.Connection):
        super().__init__(interval=MIN_SUMMARY_INTERVAL)
        self.pg_conn = pg_conn
        self.last_processed_time = 0
        self.client = AgentClient()

    async def _get_last_message_timestamp(self) -> int:
        result = await self.pg_conn.fetchval(
            "SELECT MAX(last_message_timestamp) FROM chat_score_summaries"
        )
        return max(result or 0, int(time.time()) - self.interval)

    async def process(self):
        """Evaluate all chat groups that have messages."""
        if self.last_processed_time == 0:
            self.last_processed_time = await self._get_last_message_timestamp()
        logger.info(f"Last processed time: {self.last_processed_time}")

        # Get all unique chat IDs
        current_time = int(time.time())
        chat_ids = await self.pg_conn.fetch(
            """
            SELECT DISTINCT chat_id FROM chat_messages
            WHERE message_timestamp > $1 AND message_timestamp < $2
            """,
            self.last_processed_time,
            current_time,
        )
        if not chat_ids:
            logger.info("No chat groups to process")
            return

        logger.info(f"Found {len(chat_ids)} chat groups to process")
        for record in chat_ids:
            try:
                logger.info(f"Evaluating chat {record['chat_id']} at {current_time}")
                await self.evaluate(str(record["chat_id"]), current_time)
            except Exception as e:
                logger.error(f"Error processing chat {record['chat_id']}: {e}")
        self.last_processed_time = current_time

    async def evaluate(self, chat_id: str, current_time: int) -> None:
        """Build activity report for a chat group."""
        logger.info(f"Evaluating chat {chat_id} at {current_time}")
        messages = await self.get_unprocessed_messages(chat_id, current_time)
        if not messages or len(messages) < MIN_MESSAGES_TO_PROCESS:
            logger.info(
                f"Not enough messages to process for chat {chat_id} to summarize, skipping..."
            )
            return

        logger.info(f"Found {len(messages)} messages to process for chat {chat_id}")
        # Prepare conversation history for AI
        conversation_text = self._prepare_conversations(messages)
        response = await self.client.chat_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Conversations to analyze:\n{conversation_text}",
                },
            ]
        )
        result = parse_ai_response(response, ["score", "summary", "highlights"])

        # Store the report
        logger.info(f"Storing report for chat {chat_id} at {current_time}")
        await self.pg_conn.execute(
            """
            INSERT INTO chat_score_summaries
            (chat_id, score, summary, highlights, messages_count,
             unique_users_count, last_message_timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            str(chat_id),
            int(result["score"]),
            result["summary"],
            result["highlights"],
            len(messages),
            len(set(msg["sender_id"] for msg in messages)),
            current_time,
        )

    async def get_unprocessed_messages(self, chat_id: int, current_time: int) -> list:
        query = """
            SELECT sender_id, message_text, message_timestamp
            FROM chat_messages
            WHERE chat_id = $1
            AND message_timestamp > $2
            AND message_timestamp < $3
            ORDER BY message_timestamp ASC
        """
        messages = await self.pg_conn.fetch(
            query, chat_id, self.last_processed_time, current_time
        )
        return [dict(msg) for msg in messages]

    def _prepare_conversations(self, messages: list) -> str:
        conversation_lines = []
        for msg in messages:
            # Convert epoch timestamp to ISO format
            timestamp = datetime.fromtimestamp(msg["message_timestamp"]).isoformat()
            conversation_lines.append(
                f"[{timestamp}] User {msg['sender_id']}: {msg['message_text']}"
            )
        return "\n".join(conversation_lines)
