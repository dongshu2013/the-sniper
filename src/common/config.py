import os
import time

from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
PHONE = os.getenv("TG_PHONE")
PROCESSING_INTERVAL = int(os.getenv("PROCESSING_INTERVAL", 300))
SERVICE_PREFIX = "the_sinper_bot"
SESSION_NAME = os.getenv("SESSION_NAME")

ENV = os.getenv("ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/postgres")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME: str = os.getenv("MODEL_NAME", "deepseek/deepseek-chat")


def chat_per_hour_stats_key(chat_id: str, metric: str):
    hour = int(time.time() / 3600)
    return f"{SERVICE_PREFIX}:chat:{chat_id}:per_hour_stats:{hour}:{metric}"


def message_seen_key(chat_id: str, message_id: str):
    return f"{SERVICE_PREFIX}:message:{chat_id}:{message_id}:seen"


def chat_indexed_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:indexed"
