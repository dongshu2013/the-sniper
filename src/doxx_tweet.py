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
from src.prompts.doxx_tweet_prompts import (
    SYSTEM_PROMPT,
    LEADERBOARD_PROMPT,
    MIDDAY_PROMPT,
    SENTIMENT_PROMPT,
    DEBATE_PROMPT,
    EVENING_LEADERBOARD_PROMPT,
    MIDNIGHT_MEME_PROMPT,
    MARKET_DISCOVERY_PROMPT,
    MORNING_RECAP_PROMPT,
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
    query = """
    WITH latest_summaries AS (
        SELECT DISTINCT ON (chat_id)
            chat_id, score, summary, messages_count, unique_users_count, last_message_timestamp
        FROM chat_score_summaries
        WHERE last_message_timestamp > $1
        ORDER BY chat_id, last_message_timestamp DESC
    )
    SELECT
        ls.score,
        ls.summary,
        ls.messages_count,
        ls.unique_users_count,
        cm.entity->>'reference' as reference,
        cm.entity->>'twitter_username' as twitter_username,
        cm.entity as metadata
    FROM latest_summaries ls
    JOIN chat_metadata cm ON ls.chat_id = cm.chat_id
    WHERE cm.entity->>'type' = 'meme_coin'
    ORDER BY ls.score DESC;
    """
    logger.info(f"Getting chat scores and summary")
    last_message_ts = int(time.time() - MIN_SUMMARY_INTERVAL)
    logger.info(f"Last message timestamp: {last_message_ts}")
    results = await pg_conn.fetch(query, last_message_ts)
    logger.info(f"Found {len(results)} meme coins chat groups")

    if not results:
        logger.info("No data available for leaderboard")
        return "🤔 Hmm... It's unusually quiet in the meme coin world right now! Stay tuned for more updates as communities wake up! 💤"

    max_user_count = max(result["unique_users_count"] for result in results)
    max_msg_count = max(result["messages_count"] for result in results)

    leaderboard_items = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        # Normalize unique users (0-10)
        normalized_users = normalize_score(result["unique_users_count"], max_user_count)
        normalized_messages = normalize_score(result["messages_count"], max_msg_count)
        content_quality = float(result["score"])
        final_score = (
            (content_quality * 0.6)
            + (normalized_users * 0.3)
            + (normalized_messages * 0.1)
        )
        leaderboard_items.append(
            {
                "symbol": metadata.symbol,
                "final_score": final_score,
                "summary": result["summary"],
                "twitter_username": result["twitter_username"],
            }
        )

    # sort by final score
    leaderboard_text = ""
    leaderboard_items.sort(key=lambda x: x["final_score"], reverse=True)
    for item in leaderboard_items:
        score = f"Score: {item['final_score']:.1f}"
        twitter = (
            f"twitter: @{item['twitter_username']}" if item["twitter_username"] else ""
        )
        leaderboard_text += (
            f"${item['symbol']} ({score} {twitter}): {item['summary']}\n"
        )

    user_prompts = LEADERBOARD_PROMPT.format(leaderboard_text=leaderboard_text)
    logger.info(f"User prompt: {user_prompts}")

    logger.info(f"Sending to agent")
    response = await agent.chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompts},
        ]
    )
    return response["choices"][0]["message"]["content"]


async def tweet_12pm(pg_conn: asyncpg.Connection):
    """Midday update with community highlights and comments"""
    query = """
    WITH ranked_messages AS (
        SELECT 
            m.chat_id,
            m.message_text,
            m.created_at,
            cm.entity as metadata,
            ROW_NUMBER() OVER (PARTITION BY m.chat_id ORDER BY m.engagement_score DESC) as rank
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        AND m.message_text IS NOT NULL
        AND LENGTH(m.message_text) > 5
    )
    SELECT 
        rm.message_text,
        rm.metadata,
        rm.created_at
    FROM ranked_messages rm
    WHERE rank = 1
    ORDER BY rm.created_at DESC
    LIMIT 3;
    """
    
    # Get messages from last 6 hours
    six_hours_ago = int(time.time() - 21600)  # 6 * 60 * 60
    results = await pg_conn.fetch(query, six_hours_ago)
    
    if not results:
        return "🦊 Midday check-in! It's a bit quiet in the meme coin world right now... Perfect time to catch up on research! Who's with me? 📚"

    highlights = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        # Clean and truncate message
        message = result["message_text"]
        if len(message) > 30:
            message = message[:27] + "..."
        
        highlights.append({
            "symbol": metadata.symbol,
            "message": message
        })

    user_prompt = MIDDAY_PROMPT.format(
        highlights="\n".join(
            f"${h['symbol']}: '{h['message']}'" 
            for h in highlights
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


async def tweet_3pm(pg_conn: asyncpg.Connection):
    """Afternoon sentiment analysis and commentary"""
    query = """
    WITH sentiment_stats AS (
        SELECT 
            m.chat_id,
            cm.entity as metadata,
            COUNT(*) as total_messages,
            COUNT(*) FILTER (WHERE m.sentiment_score > 0.6) as positive_count,
            COUNT(*) FILTER (WHERE m.sentiment_score < 0.4) as negative_count,
            AVG(m.sentiment_score) as avg_sentiment,
            MAX(m.engagement_score) as max_engagement
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        GROUP BY m.chat_id, cm.entity
    )
    SELECT 
        metadata,
        total_messages,
        ROUND((positive_count::float / NULLIF(total_messages, 0) * 100)::numeric, 1) as positive_percentage,
        ROUND((negative_count::float / NULLIF(total_messages, 0) * 100)::numeric, 1) as negative_percentage,
        avg_sentiment,
        max_engagement
    FROM sentiment_stats
    WHERE total_messages > 10
    ORDER BY max_engagement DESC
    LIMIT 5;
    """
    
    # Get data from last 4 hours
    four_hours_ago = int(time.time() - 14400)  # 4 * 60 * 60
    results = await pg_conn.fetch(query, four_hours_ago)
    
    if not results:
        return "🌡️ Sentiment Check: The meme coin world is taking a breather! Sometimes silence speaks volumes. What are you watching right now? 👀"

    sentiment_data = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        
        # Calculate sentiment description
        pos_pct = float(result["positive_percentage"] or 0)
        neg_pct = float(result["negative_percentage"] or 0)
        neutral_pct = 100 - (pos_pct + neg_pct)
        
        sentiment_desc = ""
        if pos_pct > 70:
            sentiment_desc = "extremely bullish"
        elif pos_pct > 50:
            sentiment_desc = "mostly positive"
        elif neg_pct > 70:
            sentiment_desc = "highly skeptical"
        elif neg_pct > 50:
            sentiment_desc = "cautious"
        else:
            sentiment_desc = "mixed feelings"
        
        sentiment_data.append({
            "symbol": metadata.symbol,
            "sentiment_desc": sentiment_desc,
            "positive": pos_pct,
            "negative": neg_pct,
            "neutral": neutral_pct,
            "message_count": result["total_messages"],
            "avg_sentiment": float(result["avg_sentiment"] or 0)
        })

    user_prompt = SENTIMENT_PROMPT.format(
        sentiment_data="\n".join(
            f"${s['symbol']}: {s['sentiment_desc']} "
            f"({s['positive']:.0f}% 📈, {s['negative']:.0f}% 📉, {s['neutral']:.0f}% 😐) "
            f"- {s['message_count']} messages"
            for s in sentiment_data
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


async def tweet_6pm(pg_conn: asyncpg.Connection):
    """Evening community debate highlights and personal opinion"""
    query = """
    WITH debate_messages AS (
        SELECT 
            m.chat_id,
            m.message_text,
            m.sentiment_score,
            m.engagement_score,
            m.created_at,
            cm.entity as metadata,
            COUNT(*) OVER (PARTITION BY m.chat_id) as chat_message_count
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        AND m.message_text IS NOT NULL
        AND LENGTH(m.message_text) > 10
    )
    SELECT 
        chat_id,
        metadata,
        ARRAY_AGG(
            json_build_object(
                'text', message_text,
                'sentiment', sentiment_score,
                'engagement', engagement_score
            )
            ORDER BY engagement_score DESC
        ) as messages
    FROM debate_messages
    WHERE chat_message_count >= 10
    GROUP BY chat_id, metadata
    ORDER BY MAX(engagement_score) DESC
    LIMIT 3;
    """
    
    # Get messages from last 3 hours
    three_hours_ago = int(time.time() - 10800)  # 3 * 60 * 60
    results = await pg_conn.fetch(query, three_hours_ago)
    
    if not results:
        return "🔥 Evening check! The debate rooms are cooling down... Perfect time to research and plan your next moves! What projects are you analyzing? 🤔"

    debates = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        messages = result["messages"]
        
        # Split messages into bullish and bearish
        bullish_msgs = []
        bearish_msgs = []
        
        for msg in messages:
            sentiment = float(msg["sentiment"])
            text = msg["text"]
            # Clean and truncate message
            if len(text) > 40:
                text = text[:37] + "..."
            
            if sentiment > 0.6:
                bullish_msgs.append(text)
            elif sentiment < 0.4:
                bearish_msgs.append(text)
        
        # Get the most engaging messages from each side
        bull_quote = bullish_msgs[0] if bullish_msgs else "Staying optimistic!"
        bear_quote = bearish_msgs[0] if bearish_msgs else "Being cautious..."
        
        debates.append({
            "symbol": metadata.symbol,
            "bull_quote": bull_quote,
            "bear_quote": bear_quote,
            "intensity": len(messages)
        })

    user_prompt = DEBATE_PROMPT.format(
        debates="\n".join(
            f"${d['symbol']} Debate:\n"
            f"Bulls: '{d['bull_quote']}'\n"
            f"Bears: '{d['bear_quote']}'\n"
            f"Heat level: {'🔥' * min(5, d['intensity'] // 10)}"
            for d in debates
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


async def tweet_9pm(pg_conn: asyncpg.Connection):
    """Evening leaderboard update with fun interaction"""
    query = """
    WITH latest_activity AS (
        SELECT 
            m.chat_id,
            cm.entity as metadata,
            COUNT(*) as message_count,
            COUNT(DISTINCT m.user_id) as active_users,
            AVG(m.sentiment_score) as avg_sentiment,
            MAX(m.engagement_score) as max_engagement,
            SUM(CASE WHEN m.sentiment_score > 0.6 THEN 1 ELSE 0 END) as bullish_count
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        GROUP BY m.chat_id, cm.entity
    )
    SELECT 
        metadata,
        message_count,
        active_users,
        avg_sentiment,
        max_engagement,
        ROUND((bullish_count::float / message_count * 100)::numeric, 1) as bullish_percentage
    FROM latest_activity
    WHERE message_count >= 20
    ORDER BY max_engagement DESC, active_users DESC
    LIMIT 5;
    """
    
    # Get data from last 6 hours
    six_hours_ago = int(time.time() - 21600)  # 6 * 60 * 60
    results = await pg_conn.fetch(query, six_hours_ago)
    
    if not results:
        return "🌙 Night check! Market's taking a breather... Perfect time to do your research! What gems are you watching? 👀"

    leaderboard = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        
        # Determine activity description
        activity_desc = ""
        if result["message_count"] > 100 and result["bullish_percentage"] > 70:
            activity_desc = "community is going wild"
        elif result["active_users"] > 50:
            activity_desc = "massive community engagement"
        elif float(result["avg_sentiment"]) > 0.7:
            activity_desc = "extremely bullish vibes"
        elif result["bullish_percentage"] > 60:
            activity_desc = "steady positive momentum"
        else:
            activity_desc = "active discussions ongoing"
        
        leaderboard.append({
            "symbol": metadata.symbol,
            "description": activity_desc,
            "active_users": result["active_users"],
            "message_count": result["message_count"],
            "bullish_pct": float(result["bullish_percentage"]),
            "engagement": float(result["max_engagement"])
        })

    user_prompt = EVENING_LEADERBOARD_PROMPT.format(
        leaderboard="\n".join(
            f"${l['symbol']}: {l['description']} "
            f"({l['active_users']} active users, {l['bullish_pct']:.0f}% bullish)"
            for l in leaderboard
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


async def tweet_12am(pg_conn: asyncpg.Connection):
    """Midnight meme post and self-talk"""
    query = """
    WITH price_changes AS (
        SELECT 
            cm.entity as metadata,
            m.chat_id,
            COUNT(*) as message_count,
            COUNT(DISTINCT m.user_id) as unique_users,
            AVG(CASE 
                WHEN m.message_text ~* 'dump|dip|crash|down|red' THEN -1
                WHEN m.message_text ~* 'pump|moon|up|green|ath' THEN 1
                ELSE 0
            END) as price_sentiment,
            AVG(m.sentiment_score) as avg_sentiment
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        GROUP BY cm.entity, m.chat_id
    )
    SELECT 
        metadata,
        message_count,
        unique_users,
        price_sentiment,
        avg_sentiment
    FROM price_changes
    WHERE message_count >= 30
    ORDER BY ABS(price_sentiment) DESC, message_count DESC
    LIMIT 3;
    """
    
    # Get data from last 4 hours
    four_hours_ago = int(time.time() - 14400)  # 4 * 60 * 60
    results = await pg_conn.fetch(query, four_hours_ago)
    
    if not results:
        return "🌙 Midnight meme check! Everyone's probably dreaming of green candles right now! 😴 What memes are living rent-free in your head? Share them below! 🎭"

    meme_data = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        
        # Determine market mood
        price_sentiment = float(result["price_sentiment"] or 0)
        avg_sentiment = float(result["avg_sentiment"] or 0.5)
        
        mood = ""
        if price_sentiment < -0.3 and avg_sentiment < 0.4:
            mood = "coping with dips"
        elif price_sentiment < 0 and avg_sentiment > 0.6:
            mood = "buying the dip"
        elif price_sentiment > 0.3 and avg_sentiment > 0.6:
            mood = "celebrating gains"
        elif price_sentiment > 0 and avg_sentiment < 0.4:
            mood = "cautiously optimistic"
        else:
            mood = "watching charts"
        
        meme_data.append({
            "symbol": metadata.symbol,
            "mood": mood,
            "active_users": result["unique_users"],
            "message_count": result["message_count"],
            "sentiment": avg_sentiment
        })

    user_prompt = MIDNIGHT_MEME_PROMPT.format(
        meme_data="\n".join(
            f"${m['symbol']}: Community {m['mood']} "
            f"({m['active_users']} traders {'😅' if m['sentiment'] < 0.5 else '🚀'})"
            for m in meme_data
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


async def tweet_3am(pg_conn: asyncpg.Connection):
    """Late night market discovery and personal updates"""
    query = """
    WITH recent_activity AS (
        SELECT 
            m.chat_id,
            cm.entity as metadata,
            COUNT(*) as message_count,
            COUNT(DISTINCT m.user_id) as unique_users,
            MAX(m.engagement_score) as peak_engagement,
            AVG(m.sentiment_score) as avg_sentiment,
            ARRAY_AGG(
                CASE WHEN m.message_text ~* 'buy|bought|whale|pump|volume' 
                THEN m.message_text ELSE NULL END
            ) FILTER (WHERE m.sentiment_score > 0.6) as bullish_messages,
            SUM(CASE 
                WHEN m.message_text ~* 'buy|bought|whale|([0-9]+k)|([0-9]+K)' 
                AND m.sentiment_score > 0.6 
                THEN 1 ELSE 0 
            END) as whale_mentions
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        GROUP BY m.chat_id, cm.entity
    )
    SELECT 
        metadata,
        message_count,
        unique_users,
        peak_engagement,
        avg_sentiment,
        bullish_messages,
        whale_mentions
    FROM recent_activity
    WHERE message_count >= 15
    AND whale_mentions > 0
    ORDER BY peak_engagement DESC, whale_mentions DESC
    LIMIT 3;
    """
    
    # Get data from last 2 hours
    two_hours_ago = int(time.time() - 7200)  # 2 * 60 * 60
    results = await pg_conn.fetch(query, two_hours_ago)
    
    if not results:
        return "👀 3AM check! Even whales need sleep... but who else is watching charts with me? ☕️ Drop your late night analysis below! 📊"

    discoveries = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        
        # Filter and clean bullish messages
        whale_messages = [
            msg for msg in result["bullish_messages"] 
            if msg and len(msg) > 10
        ]
        
        # Determine market activity level
        activity_desc = ""
        if result["whale_mentions"] > 5 and float(result["avg_sentiment"]) > 0.7:
            activity_desc = "massive whale movements"
        elif result["unique_users"] > 30:
            activity_desc = "unexpected late night action"
        elif float(result["peak_engagement"]) > 0.8:
            activity_desc = "potential breakout forming"
        else:
            activity_desc = "interesting whale watching"
        
        # Get a representative whale message if available
        whale_quote = ""
        if whale_messages:
            whale_quote = whale_messages[0]
            if len(whale_quote) > 40:
                whale_quote = whale_quote[:37] + "..."
        
        discoveries.append({
            "symbol": metadata.symbol,
            "activity": activity_desc,
            "whale_quote": whale_quote,
            "active_users": result["unique_users"],
            "sentiment": float(result["avg_sentiment"]),
            "whale_mentions": result["whale_mentions"]
        })

    user_prompt = MARKET_DISCOVERY_PROMPT.format(
        discoveries="\n".join(
            f"${d['symbol']}: {d['activity']} "
            f"({d['whale_mentions']} whale signals 🐳) "
            + (f"\nQuote: '{d['whale_quote']}'" if d['whale_quote'] else "")
            for d in discoveries
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


async def tweet_6am(pg_conn: asyncpg.Connection):
    """Morning discussion recap and motivational message"""
    query = """
    WITH night_discussions AS (
        SELECT 
            m.chat_id,
            cm.entity as metadata,
            COUNT(*) as message_count,
            COUNT(DISTINCT m.user_id) as unique_users,
            AVG(m.sentiment_score) as avg_sentiment,
            MAX(m.engagement_score) as peak_engagement,
            ARRAY_AGG(
                CASE 
                    WHEN m.engagement_score > 0.7 
                    THEN json_build_object(
                        'text', m.message_text,
                        'sentiment', m.sentiment_score,
                        'engagement', m.engagement_score
                    )
                    ELSE NULL 
                END
            ) FILTER (WHERE m.engagement_score > 0.7) as top_messages
        FROM messages m
        JOIN chat_metadata cm ON m.chat_id = cm.chat_id
        WHERE cm.entity->>'type' = 'meme_coin'
        AND m.created_at > $1
        AND m.created_at < $2
        GROUP BY m.chat_id, cm.entity
    )
    SELECT 
        metadata,
        message_count,
        unique_users,
        avg_sentiment,
        peak_engagement,
        top_messages
    FROM night_discussions
    WHERE message_count >= 25
    ORDER BY peak_engagement DESC, message_count DESC
    LIMIT 3;
    """
    
    # Get data from 6 hours ago to 1 hour ago
    six_hours_ago = int(time.time() - 21600)  # 6 * 60 * 60
    one_hour_ago = int(time.time() - 3600)    # 1 * 60 * 60
    results = await pg_conn.fetch(query, six_hours_ago, one_hour_ago)
    
    if not results:
        return "🌅 Good morning, crypto fam! Fresh day, fresh opportunities! Remember: in meme coins, as in life, balance your passion with wisdom! What's your strategy for today? 💫"

    discussions = []
    for result in results:
        metadata = MemeCoinEntityMetadata.model_validate_json(result["metadata"])
        
        # Process top messages
        highlights = []
        if result["top_messages"]:
            for msg in result["top_messages"]:
                if msg and len(msg["text"]) > 10:
                    # Clean and truncate message
                    text = msg["text"]
                    if len(text) > 40:
                        text = text[:37] + "..."
                    highlights.append({
                        "text": text,
                        "sentiment": float(msg["sentiment"]),
                        "engagement": float(msg["engagement"])
                    })
        
        # Determine night activity description
        activity_desc = ""
        avg_sentiment = float(result["avg_sentiment"] or 0.5)
        if result["message_count"] > 100 and avg_sentiment > 0.7:
            activity_desc = "explosive night discussions"
        elif result["unique_users"] > 50:
            activity_desc = "highly active community"
        elif float(result["peak_engagement"]) > 0.8:
            activity_desc = "intense debate session"
        else:
            activity_desc = "steady night conversations"
        
        discussions.append({
            "symbol": metadata.symbol,
            "activity": activity_desc,
            "highlights": highlights[:2],  # Take top 2 highlights
            "active_users": result["unique_users"],
            "sentiment": avg_sentiment,
            "message_count": result["message_count"]
        })

    user_prompt = MORNING_RECAP_PROMPT.format(
        discussions="\n".join(
            f"${d['symbol']}: {d['activity']} "
            f"({d['active_users']} night owls, {d['message_count']} messages)"
            + (f"\nHighlights: " + " | ".join(
                f"'{h['text']}' {'🚀' if h['sentiment'] > 0.6 else '🤔'}"
                for h in d['highlights']
            ) if d['highlights'] else "")
            for d in discussions
        )
    )
    
    response = await agent.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    return response["choices"][0]["message"]["content"]


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
