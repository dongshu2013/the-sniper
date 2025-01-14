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
        chains = ["sol", "base"]
        all_data = []
        
        # Configure different filters for different chains
        chain_filters = {
            "sol": ["renounced", "frozen"],
            "base": ["not_honeypot", "verified", "renounced"]
        }
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            for chain in chains:
                url = f"https://gmgn.ai/defi/quotation/v1/rank/{chain}/swaps/24h"
                params = {
                    "orderby": "volume",
                    "direction": "desc",
                    "filters[]": chain_filters[chain]
                }
                
                try:
                    logger.info(f"Fetching data for chain {chain} with params: {params}")
                    async with session.get(url, params=params) as response:
                        response_text = await response.text()
                        logger.info(f"Response status for {chain}: {response.status}")
                        logger.debug(f"Response content for {chain}: {response_text[:200]}...")  # 记录前200个字符
                        
                        if response.status == 200:
                            data = json.loads(response_text)
                            items = data.get("data", {}).get("rank", [])
                            logger.info(f"Retrieved {len(items)} items for chain {chain}")
                            
                            for item in items:
                                meme_data = MemeData(
                                    chain=item["chain"],
                                    address=item["address"],
                                    ticker=item["symbol"],
                                    tme_link=item.get("telegram"),
                                    twitter=item.get("twitter_username"),
                                    website=item.get("website")
                                )
                                all_data.append(meme_data)
                        elif response.status == 429:
                            logger.warning(f"Rate limited for chain {chain}")
                            await asyncio.sleep(60)
                        else:
                            logger.error(f"Unexpected status code {response.status} for chain {chain}")
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error for chain {chain}: {e}")
                except Exception as e:
                    logger.error(f"Error fetching data for chain {chain}: {e}", exc_info=True)
                
                await asyncio.sleep(2)
                
        logger.info(f"Total data collected: {len(all_data)} items")
        return all_data

    async def process_meme_data(self):
        try:
            meme_data = await self.fetch_gmgn_data()
            
            values = [(
                data.tme_link,
                'meme_project',
                'https://gmgn.ai/',
                data.twitter,
                data.website,
                json.dumps({
                    "chain": data.chain,
                    "address": data.address,
                    "ticker": data.ticker
                }),
                int(time.time())
            ) for data in meme_data]
            
            await self.pg_conn.executemany("""
                INSERT INTO chat_metadata (
                    tme_link, category, source_link, twitter, 
                    website, entity, processed_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (entity)
                DO UPDATE SET
                    tme_link = EXCLUDED.tme_link,
                    twitter = EXCLUDED.twitter,
                    website = EXCLUDED.website,
                    entity = EXCLUDED.entity,
                    processed_at = EXCLUDED.processed_at,
                    updated_at = CURRENT_TIMESTAMP
                """, values)
                
            logger.info(f"Successfully processed {len(meme_data)} meme tokens")
            
        except Exception as e:
            logger.error(f"Error processing meme data: {e}") 