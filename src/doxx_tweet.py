import asyncio
import logging
import os
import time
from datetime import datetime, timezone
import random
import json

import asyncpg
import tweepy
from redis.asyncio import Redis

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL, REDIS_URL
from src.common.types import MemeCoinEntityMetadata
from src.processors.score_summarizer import MIN_SUMMARY_INTERVAL
from src.prompts.doxx_tweet_prompts import (
    SYSTEM_PROMPT,
    MORNING_PRAISE_PROMPT,
    EVENING_CRITIQUE_PROMPT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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


def normalize_score(value, max_value, min_value=0):
    """Normalize a value to a 0-10 scale"""
    if max_value == min_value:
        return 0
    return ((value - min_value) / (max_value - min_value)) * 10


async def tweet_9am(pg_conn: asyncpg.Connection):
    """Morning praise tweet for high quality community."""
    chat = await get_random_top_quality_chat(pg_conn)

    if not chat:
        return "🌅 Good morning crypto world! Looking for amazing communities to highlight today! Any suggestions? 💭"
    
    # Format entity info
    entity_info = ""
    if chat["entity"]:
        entity = json.loads(chat["entity"])
        logger.info(f"---json entity: {entity}")
        if isinstance(entity, dict):
            if "name" in entity:
                entity_info += f"Project: {entity['name']}\n"
            if "website" in entity and entity["website"]:
                entity_info += f"Website: {entity['website']}\n"
            if "social" in entity and isinstance(entity["social"], dict):
                if "twitter" in entity["social"]:
                    entity_info += f"Twitter: @{entity['social']['twitter'].split('/')[-1]}\n"
    
    logger.info(f"---entity_info: {entity_info}")
    user_prompt = MORNING_PRAISE_PROMPT.format(
        name=chat["name"],
        about=chat["about"],
        ai_about=chat["ai_about"],
        category=chat["category"],
        entity_info=entity_info
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response

async def tweet_9pm(pg_conn: asyncpg.Connection):
    """Evening constructive critique tweet."""
    chat = await get_random_top_quality_chat(pg_conn)
    if not chat:
        return "🌙 Evening check! Still searching for communities to review... What groups caught your attention today? 🤔"
    
    # Format entity info (same as morning praise)
    entity_info = ""
    if chat["entity"]:
        entity = json.loads(chat["entity"])
        if isinstance(entity, dict):
            if "name" in entity:
                entity_info += f"Project: {entity['name']}\n"
            if "website" in entity and entity["website"]:
                entity_info += f"Website: {entity['website']}\n"
            if "social" in entity and isinstance(entity["social"], dict):
                if "twitter" in entity["social"]:
                    entity_info += f"Twitter: @{entity['social']['twitter'].split('/')[-1]}\n"
    
    user_prompt = EVENING_CRITIQUE_PROMPT.format(
        name=chat["name"],
        about=chat["about"],
        ai_about=chat["ai_about"],
        category=chat["category"],
        entity_info=entity_info
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response

async def get_random_top_quality_chat(pg_conn: asyncpg.Connection) -> dict:
    """Get a random chat from top 10 quality chats."""
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
    ORDER BY quality_score DESC
    LIMIT 10
    """
    
    results = await pg_conn.fetch(query)
    if not results:
        return None
    
    # Randomly select one from top 10
    selected = random.choice(results)
    return dict(selected)

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


tweet_schedule = {
    9: tweet_9am,
    21: tweet_9pm,
}


async def run(dry_run: bool = False, target_hour: int = None):
    utc_now = datetime.now(timezone.utc)
    current_hour = utc_now.hour
    current_timestamp = int(time.time())
    pg_conn = await asyncpg.connect(DATABASE_URL)

    if target_hour is not None:
        current_hour = target_hour

    try:
        # Check if we should tweet
        if current_hour in tweet_schedule:
            # Check if we already tweeted this hour (within last 2 hours)
            two_hours_ago = current_timestamp - 7200
            already_tweeted = await pg_conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM character_tweets
                    WHERE character = 'doxx'
                    AND posted_at > $1
                    AND posted_at <= $2
                )
            """,
                two_hours_ago,
                current_timestamp,
            )

            if dry_run or not already_tweeted:
                try:
                    tweet_text = await tweet_schedule[current_hour](pg_conn)
                    logger.info(f"Tweet text: {tweet_text}")
                    threads = tweet_text.split("\n")
                    if not threads:
                        logger.info("No tweet text to post")
                        return

                    if dry_run:
                        logger.info("[DRY RUN] Would tweet: \n" + "\n".join(threads))
                    else:
                        tweet(threads)
                        # Store tweet in database
                        await pg_conn.execute(
                            """
                            INSERT INTO character_tweets (character, posted_at, tweet_text)
                            VALUES ($1, $2, $3)
                        """,
                            "doxx",
                            current_timestamp,
                            tweet_text,
                        )
                except Exception as e:
                    logger.error(f"Error posting tweet: {e}")
    finally:
        await pg_conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run Doxx Twitter bot")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print tweets instead of posting them"
    )
    parser.add_argument(
        "--hour",
        type=int,
        choices=[0, 3, 6, 9, 12, 15, 18, 21],
        help="Specify hour in 24-hour format (0, 3, 6, 9, 12, 15, 18, 21)",
    )
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, target_hour=args.hour))


if __name__ == "__main__":
    main()
