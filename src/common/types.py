from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict
from telethon import TelegramClient


class AccountStatus(Enum):
    ACTIVE = "active"
    BANNED = "banned"
    SUSPENDED = "suspended"
    RUNNING = "running"


class EntityType(Enum):
    MEMECOIN = "memecoin"
    TWITTER_KOL = "twitter_kol"
    UNKNOWN = "unknown"


class ChatType(Enum):
    CHANNEL = "channel"
    GIGA_GROUP = "giga_group"
    MEGA_GROUP = "mega_group"
    GROUP = "group"


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


class IpType(Enum):
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"


class ProxySettings(BaseModel):
    ip: str
    port: int
    username: str
    password: str


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


class ChatMessageButton(BaseModel):
    text: str
    url: Optional[str]
    data: Optional[str]

    class Config:
        json_serialization = {
            "exclude_none": True,  # Optional: excludes None values from JSON output
        }


class MessageReaction(BaseModel):
    emoji: str
    count: int


class ChatMessage(BaseModel):
    message_id: str
    chat_id: str
    message_text: str
    sender_id: Optional[str] = None
    reply_to: Optional[str] = None
    topic_id: Optional[str] = None
    buttons: list[ChatMessageButton] = []
    reactions: list[MessageReaction] = []
    message_timestamp: int

    class Config:
        json_serialization = {
            "exclude_none": True,  # Optional: excludes None values from JSON output
        }


class ChatMetadata(BaseModel):
    chat_id: str
    name: str
    about: Optional[str]
    username: Optional[str]
    participants_count: int
    pinned_messages: list[ChatMessage] = []
    initial_messages: list[ChatMessage] = []
    admins: list[str] = []


class Account(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int
    tg_id: str
    api_id: str
    api_hash: str
    phone: str
    status: AccountStatus
    last_active_at: int = 0
    client: Optional[TelegramClient] = None
    ip: Optional[str] = None


class Tweet(BaseModel):
    text: str
    posted_at: int
