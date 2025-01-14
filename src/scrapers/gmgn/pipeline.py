import json
import asyncpg
from ..config import POSTGRES_CONFIG

class PostgresPipeline:
    def __init__(self):
        self.conn = None
        
    async def connect(self):
        if not self.conn:
            self.conn = await asyncpg.connect(**POSTGRES_CONFIG)
            
    async def process_item(self, item):
        await self.connect()
        entity_json = json.dumps(item.entity) if item.entity else None
        
        await self.conn.execute("""
            INSERT INTO chat_metadata (
                chat_id, tme_link, name, category, source_link, 
                twitter, website, entity, about, 
                participants_count, processed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (chat_id) DO UPDATE SET
                tme_link = $2,
                name = $3,
                category = $4,
                source_link = $5,
                twitter = $6,
                website = $7,
                entity = $8,
                about = $9,
                participants_count = $10,
                processed_at = $11,
                updated_at = CURRENT_TIMESTAMP
        """, item.chat_id, item.tme_link, item.name, item.category, 
             item.source_link, item.twitter, item.website, entity_json, 
             item.about, item.participants_count, item.processed_at) 