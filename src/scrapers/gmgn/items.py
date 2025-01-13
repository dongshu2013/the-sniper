from dataclasses import dataclass

@dataclass
class GmgnItem:
    def __init__(self):
        self.ticker = None
        self.x_account = None
        self.website = None
        self.tg_account = None
        self.source = None 