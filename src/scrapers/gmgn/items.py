from dataclasses import dataclass

@dataclass
class MemeItem:
    def __init__(self):
        self.tg_account = None # telegram account of the meme
        self.source = None # source of the meme
        self.chain = None # chain of the meme
        self.address = None # address of the meme
        self.x_account = None # x account of the meme
        self.website = None # website of the meme
        self.ticker = None # ticker of the meme
        self.category = None # category of the meme
