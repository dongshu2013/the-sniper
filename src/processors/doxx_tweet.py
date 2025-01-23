import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime

import asyncpg
import pytz
import tweepy
from redis.asyncio import Redis

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL, REDIS_URL
from src.common.types import Tweet
from src.processors.processor import ProcessorBase
from src.prompts.doxx_tweet_prompts import SYSTEM_PROMPT, USER_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


MIN_TWEET_INTERVAL = 7200


TWITTER_CONSUMER_KEY = os.getenv("DOXX_TWITTER_CONSUMER_KEY")
TWITTER_CONSUMER_SECRET = os.getenv("DOXX_TWITTER_CONSUMER_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("DOXX_TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("DOXX_TWITTER_ACCESS_TOKEN_SECRET")

client = tweepy.Client(
    consumer_key=TWITTER_CONSUMER_KEY,
    consumer_secret=TWITTER_CONSUMER_SECRET,
    access_token=TWITTER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
)

redis = Redis.from_url(REDIS_URL)
agent = AgentClient()


class DoxxTweetProcessor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=3600)
        self.pg_conn = None
        self.character = "doxx"

    async def process(self, dry_run: bool = False):
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        chat = await get_random_top_quality_chat(self.pg_conn)
        if not chat:
            return

        logger.info(f"Getting chat: {chat}")
        latest_tweets = await self.get_last_10_tweets()
        if not await should_tweeet(latest_tweets):
            return

        previous_tweets = "\n".join(
            [
                f"{tweet.text} (Posted at {format_time(tweet.posted_at)})"
                for tweet in latest_tweets
            ]
        )
        la_tz = pytz.timezone("America/Los_Angeles")
        current_time = datetime.now(la_tz).strftime("%Y-%m-%d %H:%M:%S")
        about = chat.get("about", None) or chat.get("about", "No Data")
        entity = format_entity_info(chat)
        context = f"""
Community Basic Info:
Group Name: {chat["name"]}
Description: {about}
Category: {chat["category"]}

Entity Extracted from group:
{entity}

Quality Score:
{chat["quality_score"]}

Previous Tweets:
{previous_tweets}

Current Time:
{current_time}
"""

        logger.info(f"Context: {context}")
        user_prompt = USER_PROMPT.format(context=context)
        tweet_text = await agent.chat_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        if not tweet_text:
            logger.error("No response from agent")
            return

        if not dry_run:
            tweet([tweet_text])
            # Store tweet in database
            await self.pg_conn.execute(
                """
                INSERT INTO character_tweets (character, posted_at, tweet_text)
                VALUES ($1, $2, $3)
            """,
                "doxx",
                int(time.time()),
                tweet_text,
            )
        else:
            logger.info(f"[DRY RUN] Would tweet: {tweet_text}")

    async def get_last_10_tweets(self):
        query = """
        SELECT tweet_text, posted_at FROM character_tweets
        WHERE character = $1
        ORDER BY posted_at DESC LIMIT 10
        """
        rows = await self.pg_conn.fetch(query, self.character)
        if not rows:
            return []

        return [
            Tweet(
                text=row["tweet_text"],
                posted_at=row["posted_at"],
            )
            for row in rows
        ]


def format_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def format_entity_info(chat: dict) -> str:
    """Format entity information into a readable string.

    Args:
        chat: A dictionary containing chat metadata with an 'entity' field

    Returns:
        A formatted string containing entity information with indented nested fields
    """
    entity_info = ""
    if chat["entity"]:
        entity = json.loads(chat["entity"])
        if isinstance(entity, dict):

            def format_dict(d, indent=0):
                result = ""
                for key, value in d.items():
                    if isinstance(value, dict):
                        result += " " * indent + f"{key}:\n"
                        result += format_dict(value, indent + 2)
                    elif value:  # Only add non-empty values
                        result += " " * indent + f"{key}: {value}\n"
                return result

            entity_info = format_dict(entity)
    return entity_info


async def get_random_top_quality_chat(pg_conn: asyncpg.Connection) -> dict:
    """Get a random chat with non-null entity."""
    query = """
    SELECT
        name,
        about,
        ai_about,
        category,
        entity,
        quality_score
    FROM chat_metadata
    WHERE is_blocked = false
    AND quality_score > 0
    AND entity IS NOT NULL
    AND entity != 'null'
    AND category = 'CRYPTO_PROJECT'
    ORDER BY RANDOM()
    LIMIT 1
    """
    row = await pg_conn.fetchrow(query)
    if not row:
        return None
    return dict(row)


def tweet(tweets: list[str]):
    """Post tweet or thread of tweets if text exceeds character limit."""
    # Post as single tweet if no splitting needed
    if len(tweets) == 1:
        return client.create_tweet(text=tweets[0])

    # First tweet becomes the parent
    response = client.create_tweet(text=tweets[0])
    parent_tweet_id = response.data["id"]
    # All subsequent tweets reply to the parent
    for tweet_text in tweets[1:]:
        client.create_tweet(text=tweet_text, in_reply_to_tweet_id=parent_tweet_id)


async def should_tweeet(latest_tweets: list[Tweet]):
    if not latest_tweets:
        return True
    return latest_tweets[0].posted_at < int(time.time()) - MIN_TWEET_INTERVAL


async def main():
    parser = argparse.ArgumentParser(description="Run Doxx Twitter bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tweets instead of posting them",
    )
    args = parser.parse_args()
    await DoxxTweetProcessor().process(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
