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
        super().__init__(interval=3600 * 3)
        self.pg_conn = asyncpg.connect(DATABASE_URL)
        self.character = "doxx"

    async def process(self, dry_run: bool = False):
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        chat = await get_random_top_quality_chat(self.pg_conn)
        if not chat:
            return

        latest_tweets = await self.get_last_10_tweets()
        if not await should_tweeet(latest_tweets):
            return

        la_tz = pytz.timezone("America/Los_Angeles")
        current_time = datetime.now(la_tz).strftime("%Y-%m-%d %H:%M:%S")
        community_intro = format_entity_info(chat)

        user_prompt = USER_PROMPT.format(
            community_intro=community_intro,
            current_time=current_time,
        )
        tweet_text = await agent.chat_completion(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
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


def format_entity_info(chat: dict) -> str:
    """Format entity information into a readable string.

    Args:
        chat: A dictionary containing chat metadata with an 'entity' field

    Returns:
        A formatted string containing entity information
    """
    entity_info = ""
    if chat["entity"]:
        entity = json.loads(chat["entity"])
        if isinstance(entity, dict):
            if "name" in entity:
                entity_info += f"{entity['name']}\n"
            if "social" in entity and isinstance(entity["social"], dict):
                if "twitter" in entity["social"] and entity["social"]["twitter"]:
                    entity_info += (
                        f"Twitter: @{entity['social']['twitter'].split('/')[-1]}\n"
                    )
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


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run Doxx Twitter bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tweets instead of posting them",
    )
    args = parser.parse_args()
    asyncio.run(DoxxTweetProcessor().process(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
