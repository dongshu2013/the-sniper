import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

import aiohttp
import asyncpg
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class MemeData(BaseModel):
    chain: str
    address: str
    ticker: str
    tme_link: Optional[str]
    twitter: Optional[str]
    website: Optional[str]

class MemeCrawler:
    def __init__(self, pg_conn: asyncpg.Connection, interval: int = 3600):
        self.pg_conn = pg_conn
        self.interval = interval  # Default 1 hour
        self.running = False
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://gmgn.ai/",
        }
        
    async def start_processing(self):
        self.running = True
        while self.running:
            try:
                await self.process_meme_data()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in meme processing: {e}")
                # Add exponential backoff if rate limited
                await asyncio.sleep(min(self.interval * 2, 7200))

    async def stop_processing(self):
        self.running = False

    async def fetch_gmgn_data(self) -> List[MemeData]:
        chains = ["sol", "eth", "bsc", "arb", "base"]  # Add more chains as needed
        all_data = []
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            for chain in chains:
                url = f"https://gmgn.ai/defi/quotation/v1/rank/{chain}/swaps/24h"
                params = {
                    "orderby": "volume",
                    "direction": "desc",
                    "filters[]": ["renounced", "frozen"]
                }
                
                try:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            for item in data.get("data", {}).get("rank", []):
                                meme_data = MemeData(
                                    chain=item["chain"],
                                    address=item["address"],
                                    ticker=item["symbol"],
                                    tme_link=item.get("telegram"),
                                    twitter=item.get("twitter_username"),
                                    website=item.get("website")
                                )
                                all_data.append(meme_data)
                        elif response.status == 429:  # Rate limited
                            logger.warning(f"Rate limited for chain {chain}")
                            await asyncio.sleep(60)  # Wait before next request
                except Exception as e:
                    logger.error(f"Error fetching data for chain {chain}: {e}")
                
                await asyncio.sleep(1)  # Rate limiting between requests
                
        return all_data

    async def process_meme_data(self):
        try:
            meme_data = await self.fetch_gmgn_data()
            current_time = int(time.time())
            
            for data in meme_data:
                entity = {
                    "chain": data.chain,
                    "address": data.address,
                    "ticker": data.ticker
                }
                
                await self.pg_conn.execute("""
                    INSERT INTO chat_metadata (
                        tme_link, category, source_link, twitter, 
                        website, entity, processed_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (tme_link) 
                    DO UPDATE SET
                        twitter = EXCLUDED.twitter,
                        website = EXCLUDED.website,
                        entity = EXCLUDED.entity,
                        processed_at = EXCLUDED.processed_at,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    data.tme_link,
                    'meme_project',
                    'https://gmgn.ai/',
                    data.twitter,
                    data.website,
                    json.dumps(entity),
                    current_time
                )
                
            logger.info(f"Successfully processed {len(meme_data)} meme tokens")
            
        except Exception as e:
            logger.error(f"Error processing meme data: {e}") 