from enum import Enum
from typing import Optional

from pydantic import BaseModel


class EntityType(Enum):
    MEME_COIN = "meme_coin"
    TWITTER_KOL = "twitter_kol"


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
    about: str
    participants_count: str
    entity_id: int
    processed_at: int


class EntityGroupItem(BaseModel):
    entity_id: int
    telegram_link: str


class ChatMessage(BaseModel):
    message_id: str
    chat_id: str
    message_text: str
    sender_id: str
    message_timestamp: int
