import asyncio
import json
import logging

import aiohttp
from redis.asyncio import Redis

from src.common.config import PENDING_TG_GROUPS_KEY, REDIS_URL
from src.common.types import (
    EntityGroupItem,
    EntityType,
    MemeCoinEntity,
    MemeCoinEntityMetadata,
)
from src.processors.processor import ProcessorBase

# flake8: noqa: E501
logger = logging.getLogger(__name__)

CHAIN_FILTERS = {
    "sol": ["renounced", "frozen"],
    "base": ["not_honeypot", "verified", "renounced"],
}


async def get_gmgn_24h_ranked_groups():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://gmgn.ai/",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
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
                async with session.get(
                    GMGN_24H_VOL_RANKED_URL, params=params
                ) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        data = json.loads(response_text)
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
                    elif response.status == 429:
                        logger.error(
                            f"Failed to fetch GMGN 24h ranked groups: {response.status}"
                        )
                        await asyncio.sleep(60)
                    else:
                        logger.error(
                            f"Failed to fetch GMGN 24h ranked groups: {response.status}"
                        )
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error for chain {chain}: {e}")
            except Exception as e:
                logger.error(
                    f"Error fetching data for chain {chain}: {e}", exc_info=True
                )
            await asyncio.sleep(60)


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


class EntityImporter(ProcessorBase):
    def __init__(self, redis_client: Redis):
        super().__init__(interval=600)
        self.redis_client = redis_client

    async def process(self):
        # Collect entities from the async generator
        entities = []
        async for entity in get_gmgn_24h_ranked_groups():
            entities.append(entity)

        entities_data = [
            (
                EntityType.MEME_COIN.value,
                entity.reference,
                json.dumps(entity.metadata.model_dump()),
                entity.website,
                entity.twitter_username,
                entity.logo,
                entity.telegram,
                entity.source_link,
            )
            for entity in entities
        ]

        logger.info(f"Importing {len(entities_data)} entities")
        entity_ids = [record["id"] for record in entity_ids]
        logger.info(f"Imported {len(entity_ids)} entities")
        group_info = [
            EntityGroupItem(
                entity_id=entity_id,
                telegram_link=entity_data[6],
            ).model_dump_json()
            for entity_id, entity_data in zip(entity_ids, entities_data)
            if entity_data[6]
        ]
        logger.info(f"Importing {len(group_info)} groups")
        if group_info:
            await self.redis_client.lpush(PENDING_TG_GROUPS_KEY, *group_info)
