import os

from dotenv import load_dotenv
from redis import Redis

load_dotenv()

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
PHONE = os.getenv("TG_PHONE")
PROCESSING_INTERVAL = int(os.getenv("PROCESSING_INTERVAL", 300))
SERVICE_PREFIX = "the_sinper_bot"

# Create Redis client
redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
