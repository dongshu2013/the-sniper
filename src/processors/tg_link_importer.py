import asyncio
import json
import logging
import os
import random
from typing import Optional

import asyncpg
import cloudscraper
from cloudscraper.exceptions import CloudflareChallengeError

from src.common.config import DATABASE_URL
from src.common.types import (
    IpType,
    MemeCoinEntity,
    MemeCoinEntityMetadata,
    TgLinkStatus,
)
from src.helpers.ip_proxy_helper import pick_ip_proxy
from src.processors.processor import ProcessorBase

# flake8: noqa: E501
logger = logging.getLogger(__name__)

CHAIN_FILTERS = {
    "sol": ["renounced", "frozen"],
    "base": ["not_honeypot", "verified", "renounced"],
}


async def get_gmgn_24h_ranked_groups():
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://gmgn.ai/?chain=base",
        "Origin": "https://gmgn.ai",
    }

    for chain in ["sol", "base"]:
        GMGN_24H_VOL_RANKED_URL = (
            f"https://gmgn.ai/defi/quotation/v1/rank/{chain}/swaps/24h"
        )
        params = {
            "orderby": "volume",
            "direction": "desc",
            "filters[]": CHAIN_FILTERS[chain],
        }
        try:
            # 使用 cloudscraper 发送请求
            response = scraper.get(
                GMGN_24H_VOL_RANKED_URL, params=params, headers=headers
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("data", {}).get("rank", [])
                logger.info(f"Found {len(items)} items")
                for item in items:
                    metadata = MemeCoinEntityMetadata(
                        launchpad=item.get("launchpad", None),
                        symbol=item["symbol"],
                    )
                    reference = item["chain"] + ":" + item["address"]
                    yield MemeCoinEntity(
                        reference=reference,
                        metadata=metadata,
                        logo=item.get("logo", None),
                        twitter_username=item.get("twitter_username", None),
                        website=item.get("website", None),
                        telegram=item.get("telegram", None),
                        source_link=GMGN_24H_VOL_RANKED_URL,
                    )
            else:
                logger.error(
                    f"Failed to fetch GMGN 24h ranked groups: {response.status_code}"
                )

        except CloudflareChallengeError as e:
            logger.error(f"Cloudflare challenge error: {e}")
        except Exception as e:
            logger.error(f"Error fetching data for chain {chain}: {e}", exc_info=True)
        await asyncio.sleep(60)  # Rate limiting


async def import_gmgn_24h_ranked_groups():
    try:
        with open("data/gmgn_24h_vol_ranked.json", "r") as f:
            data = json.load(f)
            items = data.get("data", {}).get("rank", [])
            logger.info(f"Found {len(items)} items in local file")
            for item in items:
                metadata = MemeCoinEntityMetadata(
                    launchpad=item.get("launchpad", None),
                    symbol=item["symbol"],
                )
                reference = item["chain"] + ":" + item["address"]
                yield MemeCoinEntity(
                    reference=reference,
                    metadata=metadata,
                    logo=item.get("logo", None),
                    twitter_username=item.get("twitter_username", None),
                    website=item.get("website", None),
                    telegram=item.get("telegram", None),
                    source_link=f.name,
                )
    except FileNotFoundError:
        logger.error("Local JSON file not found")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
    except Exception as e:
        logger.error(f"Error reading local file: {e}", exc_info=True)


class TgLinkImporter(ProcessorBase):
    def __init__(self):
        super().__init__(interval=300)
        self.scraper = None
        self.max_retries = 3
        self.user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        ]
        self.pg_conn = None

    async def _create_scraper(self):
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        proxies = await pick_ip_proxy(self.pg_conn, IpType.RESIDENTIAL)
        proxy = proxies[0]
        proxy_url = f"http://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}"
        if os.getenv("PROXY_URL"):
            scraper.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
        return scraper

    async def _fetch_with_retry(self, url: str, params: dict) -> Optional[dict]:
        """Fetch data with retry mechanism"""
        if not self.scraper:
            self.scraper = await self._create_scraper()

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://gmgn.ai/?chain=base",
            "Origin": "https://gmgn.ai",
            "User-Agent": random.choice(self.user_agents),
            "sec-ch-ua": '"Google Chrome";v="122", "Chromium";v="122", "Not_A Brand";v="24"',
            "sec-ch-ua-platform": '"Windows"',  # Changed to Windows for better acceptance
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }

        for attempt in range(self.max_retries):
            try:
                # Randomize delay between attempts
                await asyncio.sleep(random.uniform(5, 10) * (attempt + 1))

                response = self.scraper.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=30,  # Add explicit timeout
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 403:
                    logger.warning(
                        f"403 error on attempt {attempt + 1}, recreating scraper..."
                    )
                    self.scraper = await self._create_scraper()
                    await asyncio.sleep(random.uniform(10, 15) * (attempt + 1))
                else:
                    logger.error(f"Unexpected status code: {response.status_code}")
                    await asyncio.sleep(random.uniform(7, 12))

            except CloudflareChallengeError as e:
                logger.error(
                    f"Cloudflare challenge error on attempt {attempt + 1}: {e}"
                )
                self.scraper = await self._create_scraper()
                await asyncio.sleep(random.uniform(10, 15) * (attempt + 1))
            except Exception as e:
                logger.error(
                    f"Unexpected error on attempt {attempt + 1}: {e}", exc_info=True
                )
                await asyncio.sleep(random.uniform(7, 12))

        return None

    async def process(self):
        """Main processing logic"""
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        entities = []

        for chain in ["sol", "base"]:
            url = f"https://gmgn.ai/defi/quotation/v1/rank/{chain}/swaps/24h"
            params = {
                "orderby": "volume",
                "direction": "desc",
                "filters[]": CHAIN_FILTERS[chain],
            }

            data = await self._fetch_with_retry(url, params)

            if data:
                items = data.get("data", {}).get("rank", [])
                logger.info(f"Found {len(items)} items for chain {chain}")

                for item in items:
                    metadata = MemeCoinEntityMetadata(
                        launchpad=item.get("launchpad", None),
                        symbol=item["symbol"],
                    )
                    reference = item["chain"] + ":" + item["address"]
                    entities.append(
                        MemeCoinEntity(
                            reference=reference,
                            metadata=metadata,
                            logo=item.get("logo", None),
                            twitter_username=item.get("twitter_username", None),
                            website=item.get("website", None),
                            telegram=item.get("telegram", None),
                            source_link=url,
                        )
                    )
            else:
                logger.error(f"Failed to fetch data for chain {chain}")
            await asyncio.sleep(10)  # Add delay between processing different chains

        if not entities:
            logger.warning("No entities found from either API or local file")
            return

        tg_links = [entity.telegram for entity in entities if entity.telegram]

        if not tg_links:
            logger.info("No telegram links found")
            return

        logger.info(f"Importing {len(tg_links)} telegram links")
        await self.pg_conn.executemany(
            """
            INSERT INTO tg_link_status (tg_link, status)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            [(link, TgLinkStatus.PENDING_PRE_PROCESSING.value) for link in tg_links],
        )
        logger.info(f"Imported {len(tg_links)} telegram links")
