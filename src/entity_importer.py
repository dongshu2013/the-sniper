import asyncio
import json
import logging

import asyncpg
import requests
from redis.asyncio import Redis

from src.common.config import DATABASE_URL, PENDING_TG_GROUPS_KEY, REDIS_URL
from src.common.types import (
    EntityGroupItem,
    EntityType,
    MemeCoinEntity,
    MemeCoinEntityMetadata,
)

# flake8: noqa: E501
GMGM_24H_RANKED = "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps/24h?orderby=volume&direction=desc&filters%5B%5D=renounced&filters%5B%5D=frozen"

logger = logging.getLogger(__name__)
logger.basicConfig(level=logging.INFO)


def get_gmgn_24h_ranked_groups():
    response = requests.get(GMGM_24H_RANKED)
    if response.status_code != 200:
        return []
    result = response.json()
    items = result["data"]["rank"]
    for item in items:
        metadata = MemeCoinEntityMetadata(
            launchpad=item["launchpad"],
            symbol=item["symbol"],
        )
        reference = item["chain"] + ":" + item["address"]
        yield MemeCoinEntity(
            reference=reference,
            metadata=metadata,
            logo=item["logo"],
            twitter_username=item["twitter_username"],
            website=item["website"],
            telegram=item["telegram"],
            source_link=GMGM_24H_RANKED,
        )


class EntityImporter:
    def __init__(self, pg_conn: asyncpg.Connection, redis_client: Redis):
        self.running = False
        self.pg_conn = pg_conn
        self.redis_client = redis_client
        self.interval = 300

    async def start_processing(self):
        self.running = True
        while self.running:
            await self.process()
            await asyncio.sleep(self.interval)

    async def stop_processing(self):
        self.running = False

    async def process(self):
        async with self.pg_conn.connection() as conn:
            # Prepare all entities data as a list of tuples
            entities_data = [
                (
                    EntityType.MEME_COIN.value,
                    entity.reference,
                    entity.metadata.model_dump(),
                    entity.website,
                    entity.twitter_username,
                    entity.logo,
                    entity.telegram,
                    entity.source_link,
                )
                for entity in get_gmgn_24h_ranked_groups()
            ]

            entity_ids = await conn.executemany(
                """
                INSERT INTO entities (
                    entity_type, reference, metadata, website,
                    twitter_username, logo, telegram, source_link
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (entity_type, reference) DO UPDATE
                SET
                    logo = EXCLUDED.logo,
                    website = EXCLUDED.website,
                    telegram = EXCLUDED.telegram,
                    twitter_username = EXCLUDED.twitter_username,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                entities_data,
            )
            group_info = [
                EntityGroupItem(
                    entity_id=entity_id,
                    telegram_link=entity_data[6],
                ).model_dump_json()
                for entity_id, entity_data in zip(entity_ids, entities_data)
                if entity_data[6]
            ]
            await self.redis_client.lpush(PENDING_TG_GROUPS_KEY, *group_info)


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)
    redis_client = Redis.from_url(REDIS_URL)
    entity_importer = EntityImporter(pg_conn, redis_client)
    try:
        await asyncio.gather(
            entity_importer.start_processing(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await entity_importer.stop_processing()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
