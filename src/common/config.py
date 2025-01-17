import os
import time

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/postgres")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME: str = os.getenv("MODEL_NAME", "deepseek/deepseek-chat")

SERVICE_PREFIX = "the_sinper_bot"
MESSAGE_QUEUE_KEY = f"{SERVICE_PREFIX}:message_queue"


def chat_per_hour_stats_key(chat_id: str, metric: str):
    hour = int(time.time() / 3600)
    return f"{SERVICE_PREFIX}:chat:{chat_id}:per_hour_stats:{hour}:{metric}"


def message_seen_key(chat_id: str, message_id: str):
    return f"{SERVICE_PREFIX}:message:{chat_id}:{message_id}:seen"


def chat_watched_by_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:watched_by"
