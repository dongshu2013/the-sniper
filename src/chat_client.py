import asyncio
import logging
from typing import List

import asyncpg
import yaml
from redis.asyncio import Redis
from telethon import TelegramClient, events

from src.common.config import (
    DATABASE_URL,
    MESSAGE_QUEUE_KEY,
    REDIS_URL,
    chat_per_hour_stats_key,
    message_seen_key,
)
from src.common.types import ChatMessage
from src.processors.group_processor import GroupProcessor
from src.processors.tg_link_pre_processor import TgLinkPreProcessor

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)


class TelegramAccountConfig:
    def __init__(self, session_name: str, api_id: str, api_hash: str, phone: str):
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone


def load_telegram_configs(config_path: str) -> List[TelegramAccountConfig]:
    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)

    accounts = []
    for account in config_data["telegram_accounts"]:
        accounts.append(
            TelegramAccountConfig(
                session_name=account["session_name"],
                api_id=account["api_id"],
                api_hash=account["api_hash"],
                phone=account["phone"],
            )
        )
    return accounts


async def run():
    pg_conn = await asyncpg.connect(DATABASE_URL)

    # Load configs and create clients
    accounts = load_telegram_configs("config/config.yaml")
    clients = []
    for account in accounts:
        client = TelegramClient(account.session_name, account.api_id, account.api_hash)
        await client.start(phone=account.phone)
        clients.append(client)

    logger.info(f"Started {len(clients)} Telegram clients successfully")

    tg_link_processor = TgLinkPreProcessor(clients[0], pg_conn)
    group_processors = [GroupProcessor(clients[0], pg_conn) for client in clients]

    try:
        client_tasks = [client.run_until_disconnected() for client in clients]
        group_processor_tasks = [
            grp_proc.start_processing() for grp_proc in group_processors
        ]

        await asyncio.gather(
            *client_tasks,
            tg_link_processor.start_processing(),
            *group_processor_tasks,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        for client in clients:
            await client.disconnect()


async def register_handlers(client: TelegramClient):

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        if not event.is_group or not event.is_channel:
            return

        chat_id = str(event.chat_id)
        if chat_id.startswith("-100"):
            chat_id = chat_id[4:]

        message_id = str(event.id)
        if await redis_client.exists(message_seen_key(chat_id, message_id)):
            return

        message_data = ChatMessage(
            message_id=message_id,
            chat_id=chat_id,
            message_text=event.message.text,
            sender_id=str(event.sender_id),
            message_timestamp=int(event.date.timestamp()),
        )
        pipeline = redis_client.pipeline()
        pipeline.incr(chat_per_hour_stats_key(chat_id, "messages_count"))
        pipeline.set(message_seen_key(chat_id, message_id), "true")
        pipeline.lpush(MESSAGE_QUEUE_KEY, message_data.model_dump_json())
        await pipeline.execute()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
