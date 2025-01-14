import asyncio
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


def get_gmgn_24h_ranked_groups():
    response = requests.get(GMGM_24H_RANKED)
    if response.status_code != 200:
        return []
    result = response.json()
    items = result["data"]["rank"]
    logger.info(f"Found {len(items)} items")
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
        logger.info(f"Importing {len(entities_data)} entities")
        entity_ids = await self.pg_conn.fetch(
            """
            INSERT INTO entities (
                entity_type, reference, metadata, website,
                twitter_username, logo, telegram, source_link
            )
            SELECT * FROM unnest($1::text[], $2::text[], $3::jsonb[], $4::text[],
                               $5::text[], $6::text[], $7::text[], $8::text[])
            ON CONFLICT (entity_type, reference) DO UPDATE
            SET
                logo = EXCLUDED.logo,
                website = EXCLUDED.website,
                telegram = EXCLUDED.telegram,
                twitter_username = EXCLUDED.twitter_username,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            [x[0] for x in entities_data],  # entity_type
            [x[1] for x in entities_data],  # reference
            [x[2] for x in entities_data],  # metadata
            [x[3] for x in entities_data],  # website
            [x[4] for x in entities_data],  # twitter_username
            [x[5] for x in entities_data],  # logo
            [x[6] for x in entities_data],  # telegram
            [x[7] for x in entities_data],  # source_link
        )
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


async def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.setLevel(logging.INFO)
    logger.info("Starting entity importer...")

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
