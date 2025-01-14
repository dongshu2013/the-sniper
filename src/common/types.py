from enum import Enum

from pydantic import BaseModel


class EntityType(Enum):
    MEME_COIN = "meme_coin"
    TWITTER_KOL = "twitter_kol"


class MemeCoinEntityMetadata(BaseModel):
    symbol: str
    launchpad: str


class MemeCoinEntity(BaseModel):
    reference: str
    metadata: MemeCoinEntityMetadata
    logo: str
    twitter_username: str
    website: str
    telegram: str
    source_link: str


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
