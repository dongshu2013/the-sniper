#     ### Full-Day Posting Schedule:
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
from datetime import datetime

import asyncpg
import tweepy
from redis.asyncio import Redis

from src.common.agent_client import AgentClient
from src.common.config import DATABASE_URL, REDIS_URL
from src.processors.score_summary import MIN_SUMMARY_INTERVAL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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


def calculate_score(scores):
    if not scores:
        return 0

    # Get max values for normalization
    max_user_count = max(score["unique_user_count"] for score in scores)
    max_msg_count = max(score["messages_count"] for score in scores)

    final_scores = 0
    for chat_id, score in scores.items():
        # Normalize unique users (0-10)
        normalized_users = normalize_score(score["unique_user_count"], max_user_count)
        normalized_messages = normalize_score(score["messages_count"], max_msg_count)
        content_quality = float(score["score"])
        chat_score = (
            (content_quality * 0.6)
            + (normalized_users * 0.3)
            + (normalized_messages * 0.1)
        )
        final_scores[chat_id] = chat_score
    return final_scores


async def read_chat_score_summary(pg_conn: asyncpg.Connection) -> dict:
    query = """
SELECT chat_id, score, summary, messages_count, unique_users_count, last_message_timestamp
FROM chat_score_summaries
WHERE last_message_timestamp > $1
ORDER BY score DESC
LIMIT 10
"""
    last_message_ts = int(time.time() - MIN_SUMMARY_INTERVAL)
    results = await pg_conn.fetch(query, last_message_ts)
    chat_scores = {}
    final_results = {}
    for result in results:
        chat_id = result["chat_id"]
        score = result["score"]
        messages_count = result["messages_count"]
        unique_users_count = result["unique_users_count"]
        chat_scores[chat_id] = {
            "score": score,
            "messages_count": messages_count,
            "unique_users_count": unique_users_count,
        }
        final_results[chat_id] = {"summary": result["summary"]}
    final_scores = calculate_score(chat_scores)
    for chat_id, score in final_scores.items():
        final_results[chat_id]["final_score"] = score

    # Format the results into text
    leaderboard_text = ""
    for chat_id, result in final_results.items():
        leaderboard_text += (
            f"{chat_id} (Score: {result['final_score']:.1f}): {result['summary']}\n"
        )

    user_prompts = LEADERBOARD_PROMPT.format(leaderboard_text=leaderboard_text)
    logger.info(f"User prompt: {user_prompts}")
    response = await agent.chat_completion(
        [
            {"role": "system", "content": SYSTME_PROMPT},
            {"role": "user", "content": user_prompts},
        ]
    )
    return response["choices"][0]["message"]["content"]


def read_highlights() -> str:
    pass


def tweet_9am():
    pass


def tweet_12pm():
    pass


def tweet_3pm():
    pass


def tweet_6pm():
    pass


def tweet_9pm():
    pass


def tweet_12am():
    pass


def tweet_3am():
    pass


def tweet_6am():
    pass


def tweet(text: str):
    client.create_tweet(text=text)


async def run(dry_run: bool = False):
    # Get current time in UTC
    utc_now = datetime.now(datetime.timezone.utc)
    current_hour = utc_now.hour
    current_date = utc_now.date().isoformat()
    pg_conn = await asyncpg.connect(DATABASE_URL)

    # Create a Redis key for the current hour and date
    redis_key = f"doxx_tweet:{current_date}:{current_hour}"

    # Map hours to tweet functions
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

    # Check if we should tweet
    if current_hour in tweet_schedule:
        # Check if we already tweeted this hour
        if not await redis.exists(redis_key):
            try:
                tweet_text = tweet_schedule[current_hour]()
                if dry_run:
                    print(f"[DRY RUN] Would tweet: {tweet_text}")
                else:
                    tweet(tweet_text)
                    # Set key with 2 hour expiration (safe cleanup)
                    await redis.setex(redis_key, 7200, "tweeted")
            except Exception as e:
                print(f"Error posting tweet: {e}")


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
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
