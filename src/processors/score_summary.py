import asyncio
import json
import logging
from asyncio.log import logger
from datetime import datetime

import asyncpg
from redis.asyncio import Redis

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL, REDIS_URL, chat_info_key

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
  - reason: The reason why you give the score.
"""
# format on

MIN_MESSAGES_TO_PROCESS = 10


class ChatScoreSummaryProcessor:
    def __init__(self, interval: int = 3600 * 6):  # every 6 hours
        self.client = AgentClient()
        self.pg_conn = None
        self.redis_client = Redis.from_url(REDIS_URL)
        self.interval = interval
        self.running = False

    async def create_tables(self):
        """Create necessary tables if they don't exist."""
        await self.pg_conn.execute(
            # flake8: noqa
            # format off
            """
CREATE TABLE IF NOT EXISTS chat_score_summaries (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    score NUMERIC(3,1) NOT NULL,
    summary TEXT NOT NULL,
    reason TEXT NOT NULL,
    messages_count INTEGER NOT NULL,
    unique_users_count INTEGER NOT NULL,
    last_message_timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, last_message_timestamp)
);

-- Create index on chat_id and last_message_timestamp for faster unique constraint checks
CREATE INDEX IF NOT EXISTS idx_chat_score_summaries_chat_version ON chat_score_summaries(chat_id, last_message_timestamp);
        """
            # format on
        )

    async def start_processing(self):
        self.running = True
        # Connect to database and create table if it doesn't exist
        self.pg_conn = await asyncpg.connect(DATABASE_URL)
        await self.create_tables()

        while self.running:
            try:
                await self.evaluate()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in group processing: {e}")

    async def evaluate(self, chat_id: str) -> None:
        """Build activity report for a chat group."""
        messages = await self.get_unprocessed_messages(chat_id)
        chat_info = json.loads(await self.redis_client.get(chat_info_key(chat_id)))
        if not messages or len(messages) < MIN_MESSAGES_TO_PROCESS:
            logging.info(
                f"Not enough messages to process for chat {chat_info['name']} to summarize, skipping..."
            )
            return

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
        try:
            result = json.loads(response["choices"][0]["message"]["content"])
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            return

        # Store the report
        await self.pg_conn.execute(
            """
            INSERT INTO chat_score_summaries
            (chat_id, score, summary, reason, messages_count,
             unique_users_count, last_message_timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            chat_id,
            result["score"],
            result["summary"],
            result["reason"],
            len(messages),
            len(set(msg["sender_id"] for msg in messages)),
            max(msg["message_timestamp"] for msg in messages),
        )

    async def stop_processing(self):
        self.running = False
        if self.pg_conn:
            await self.pg_conn.close()

    async def get_unprocessed_messages(self, chat_id: int) -> list:
        query = """
            WITH last_processed AS (
                SELECT last_message_timestamp
                FROM chat_score_summaries
                WHERE chat_id = $1
                ORDER BY last_message_timestamp DESC
                LIMIT 1
            )
            SELECT sender_id, message_text, message_timestamp
            FROM chat_messages
            WHERE chat_id = $1
            AND message_timestamp > COALESCE((SELECT last_message_timestamp FROM last_processed), 0)
            ORDER BY message_timestamp ASC
        """
        messages = await self.pg_conn.fetch(query, chat_id)
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
