from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict
from telethon import TelegramClient


class AccountStatus(Enum):
    ACTIVE = "active"
    BANNED = "banned"
    SUSPENDED = "suspended"


class EntityType(Enum):
    MEMECOIN = "memecoin"
    TWITTER_KOL = "twitter_kol"
    UNKNOWN = "unknown"


class TgLinkStatus(Enum):
    PENDING_PRE_PROCESSING = "pending_pre_processing"
    PENDING_PROCESSING = "pending_processing"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"
    IGNORED = "ignored"


class AccountChatStatus(Enum):
    WATCHING = "watching"
    QUIT = "quit"


class ChatStatus(Enum):
    EVALUATING = "evaluating"
    ACTIVE = "active"
    LOW_QUALITY = "low_quality"
    BLOCKED = "blocked"


class ChatPhoto(BaseModel):
    id: str | int
    path: str


class MemeCoinEntityMetadata(BaseModel):
    symbol: str
    launchpad: Optional[str | dict]


class MemeCoinEntity(BaseModel):
    reference: str
    metadata: MemeCoinEntityMetadata
    logo: Optional[str]
    twitter_username: Optional[str]
    website: Optional[str]
    telegram: Optional[str]
    source_link: Optional[str]


class ChatMetadata(BaseModel):
    chat_id: str
    name: str
    about: Optional[str]
    participants_count: int
    processed_at: int


class ChatMessage(BaseModel):
    message_id: str
    chat_id: str
    message_text: str
    sender_id: Optional[str] = None
    reply_to: Optional[str] = None
    topic_id: Optional[str] = None
    message_timestamp: int


class Account(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: int
    tg_id: str
    api_id: str
    api_hash: str
    phone: str
    status: AccountStatus
    last_active_at: Optional[int]
    client: Optional[TelegramClient]
