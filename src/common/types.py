from enum import Enum
from typing import Optional

from pydantic import BaseModel


class EntityType(Enum):
    MEMECOIN = "memecoin"
    TWITTER_KOL = "twitter_kol"
    UNKNOWN = "unknown"


class TgLinkStatus(Enum):
    PENDING_PRE_PROCESSING = "pending_pre_processing"
    PENDING_PROCESSING = "pending_processing"
    PROCESSED = "processed"
    ERROR = "error"
    IGNORED = "ignored"


class AccountChatStatus(Enum):
    JOINED = "watching"
    QUIT = "quit"


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
    sender_id: str
    message_timestamp: int
