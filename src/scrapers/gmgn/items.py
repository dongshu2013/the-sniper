from dataclasses import dataclass

@dataclass
class ChatMetadata:
    def __init__(self):
        self.chat_id: str = None
        self.tme_link: str = None  # t.me link
        self.name: str = None
        self.category: str = None
        self.source_link: str = None
        self.twitter: str = None
        self.website: str = None
        self.entity: dict = None  # {chain, address, ticker}
        self.about: str = None
        self.participants_count: int = None
        self.processed_at: int = None
