import asyncpg
from ..config import POSTGRES_CONFIG

class PostgresPipeline:
    def __init__(self):
        self.conn = None
        
    async def connect(self):
        if not self.conn:
            self.conn = await asyncpg.connect(**POSTGRES_CONFIG)
            await self._create_table()
            
    async def _create_table(self):
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS meme_info (
                id SERIAL PRIMARY KEY,
                ticker TEXT UNIQUE,
                x_account TEXT,
                website TEXT, 
                tg_account TEXT,
                source TEXT
            )
        """)
        
    async def process_item(self, item):
        await self.connect()
        await self.conn.execute("""
            INSERT INTO meme_info (ticker, x_account, website, tg_account, source)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (ticker) DO NOTHING
        """, item.ticker, item.x_account, item.website, item.tg_account, item.source) 