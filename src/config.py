import os

from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
PHONE = os.getenv("TG_PHONE")
PROCESSING_INTERVAL = int(os.getenv("PROCESSING_INTERVAL", 300))
SERVICE_PREFIX = "the_sinper_bot"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/postgres")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def chat_watchers_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:watchers"


def chat_info_key(chat_id: str):
    return f"{SERVICE_PREFIX}:chat:{chat_id}:info"


def user_chat_key(user_id: str, chat_id: str):
    return f"{SERVICE_PREFIX}:user:{user_id}:chat:{chat_id}"
