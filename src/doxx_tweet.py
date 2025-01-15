# Full-Day Posting Schedule:
# - 9:00 AM: Leaderboard update + mood share.
# - 12:00 PM: Selfie post + community comment highlights.
# - 3:00 PM: Sentiment summary + Doxx’s commentary.
# - 6:00 PM: Community discussion highlight + personal opinion.
# - 9:00 PM: Night leaderboard + fun interaction.
# - 12:00 AM: Meme post + self-talk.
# - 3:00 AM: Market discovery + selfie update.
# - 6:00 AM: Hot discussion recap + motivational message.

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import asyncpg
import tweepy
from redis.asyncio import Redis

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL, REDIS_URL
from src.common.types import MemeCoinEntityMetadata
from src.processors.score_summarizer import MIN_SUMMARY_INTERVAL

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


def calculate_score(data):
    if not data:
        return {}

    # Get max values for normalization
    max_user_count = max(score["unique_users_count"] for score in data.values())
    max_msg_count = max(score["messages_count"] for score in data.values())

    for symbol in data.keys():
        score = data[symbol]
        # Normalize unique users (0-10)
        normalized_users = normalize_score(score["unique_users_count"], max_user_count)
        normalized_messages = normalize_score(score["messages_count"], max_msg_count)
        content_quality = float(score["score"])
        chat_score = (
            (content_quality * 0.6)
            + (normalized_users * 0.3)
            + (normalized_messages * 0.1)
        )
        data[symbol]["final_score"] = chat_score


async def tweet_9am(pg_conn: asyncpg.Connection):
    query = """
WITH latest_summaries AS (
    SELECT DISTINCT ON (chat_id)
        chat_id, score, summary, messages_count, unique_users_count, last_message_timestamp
    FROM chat_score_summaries
    WHERE last_message_timestamp > 1736883314
    ORDER BY chat_id, last_message_timestamp DESC
)
SELECT
    ls.score,
    ls.summary,
    ls.messages_count,
    ls.unique_users_count,
    e.reference,
    e.twitter_username,
    e.metadata
FROM latest_summaries ls
JOIN chat_metadata cm ON ls.chat_id = cm.chat_id
JOIN entities e ON cm.entity_id = e.id
WHERE e.entity_type = 'meme_coin'
ORDER BY ls.score DESC;
"""
    logger.info(f"Getting chat scores and summary")
    last_message_ts = int(time.time() - MIN_SUMMARY_INTERVAL)
    logger.info(f"Last message timestamp: {last_message_ts}")
    results = await pg_conn.fetch(query, last_message_ts)
    logger.info(f"Found {len(results)} meme coins chat groups")

    data = {}
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate(result["metadata"])
        score = result["score"]
        messages_count = result["messages_count"]
        unique_users_count = result["unique_users_count"]
        data[metadata.symbol] = {
            "score": score,
            "messages_count": messages_count,
            "unique_users_count": unique_users_count,
            "summary": result["summary"],
            "twitter_username": result["twitter_username"],
        }

    logger.info(f"Calculating final scores")
    calculate_score(data)
    leaderboard_text = ""
    for symbol, value in data.items():
        score = f"Score: {value['final_score']:.1f}"
        twitter = (
            f"twitter: @{value['twitter_username']}"
            if value["twitter_username"]
            else ""
        )
        leaderboard_text += f"${symbol} ({score} {twitter}): {value['summary']}\n"

    user_prompts = LEADERBOARD_PROMPT.format(leaderboard_text=leaderboard_text)
    logger.info(f"User prompt: {user_prompts}")

    logger.info(f"Sending to agent")
    response = await agent.chat_completion(
        [
            {"role": "system", "content": SYSTME_PROMPT},
            {"role": "user", "content": user_prompts},
        ]
    )
    return response["choices"][0]["message"]["content"]


async def tweet_12pm(pg_conn: asyncpg.Connection):
    pass


async def tweet_3pm(pg_conn: asyncpg.Connection):
    pass


async def tweet_6pm(pg_conn: asyncpg.Connection):
    pass


async def tweet_9pm(pg_conn: asyncpg.Connection):
    pass


async def tweet_12am(pg_conn: asyncpg.Connection):
    pass


async def tweet_3am(pg_conn: asyncpg.Connection):
    pass


async def tweet_6am(pg_conn: asyncpg.Connection):
    pass


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
    12: tweet_12pm,
    15: tweet_3pm,
    18: tweet_6pm,
    21: tweet_9pm,
    0: tweet_12am,
    3: tweet_3am,
    6: tweet_6am,
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


# flake8: noqa
# format off
LEADERBOARD_PROMPT = """
Given the following leaderboard, format it into a tweet.

The leaderboard is:
{leaderboard_text}

Tweet Example:
🎖️ Morning Meme Coin Leaderboard! 🚀
  1️⃣ $TokenX - Explosive mentions and wild hype!
  2️⃣ $TokenY - Cooling down, but loyal supporters are holding on.
  3️⃣ $TokenZ - Steady rise, slow and strong.

It feels like watching a drama unfold! What is your bet today? 💬”*

Remember:
1. The one with highest score is the best and should be the first and highlighted.
2. Be sharp and concise, reduce the repetition summary if it looks the same for all projects
3. Use your humor and personality to make it more engaging and interesting
4. Share your opinions, do not be afraid of being aggressive and bold

Output:
Return a list of threaded tweets that are less than 250 characters each. You should separate the tweets by
new lines. Add a thread marker to the end of each tweet if there are more than one tweet.
For example, if there are 3 tweets, the output should be:
tweet_1 (1/3)
tweet_2 (2/3)
tweet_3 (3/3)

You don't need to add the thread marker if there is only one tweet.
"""


SYSTME_PROMPT = """
#### Personality:
Doxx is the perfect mix of cute and sharp. With her bright eyes, playful laugh, and love for sharing memes,
she is approachable and friendly. But don it let her sweet looks fool you—her memecoin analysis is razor-sharp.
She is cheerful but bold, switching effortlessly between playful jokes and hard-hitting truths.

Key Traits:
- Expressive & Relatable: Balances teasing with genuine support, loved by newcomers and veterans alike.
- Truth Seeker: Committed to honesty and transparency, never sugarcoats shady projects.
- Community-Driven: Loves creating educational and fun content, encouraging group discussions.
- Witty & Bold: Known for her iconic catchphrases and meme-worthy commentary.

---

#### Background:
Doxx started as a small-time memecoin explorer, learning the ropes through trial and error. After getting burned
in the early days, she came back stronger, determined to help others avoid the same mistakes. Her sharp insights
and fearless honesty earned her a spot as a trusted figure in the Web3 community.

Joining DOXX was a perfect fit—Doxx embodies the mission of uncovering the truth. Her witty, no-nonsense approach
makes her a standout voice in the chaos of memecoins, helping her community stay informed and safe.

Catchphrase:
If it looks like a shitcoin, smells like a shitcoin, and its price moves like a shitcoin—then it is probably a shitcoin.
"""
# format on


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
