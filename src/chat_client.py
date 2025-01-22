import asyncio
import logging
import os

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient, events

from src.common.account import download_session_file, load_accounts, upload_session_file
from src.common.config import (
    DATABASE_URL,
    MESSAGE_QUEUE_KEY,
    REDIS_URL,
    chat_per_hour_stats_key,
    message_seen_key,
)
from src.common.types import IpType, ProxySettings
from src.helpers.ip_proxy_helper import MAX_CLIENTS_PER_IP, pick_ip_proxy
from src.helpers.message_helper import to_chat_message
from src.processors.account_heartbeat_processor import AccountHeartbeatProcessor
from src.processors.group_processor import GroupProcessor
from src.processors.tg_link_pre_processor import TgLinkPreProcessor

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)
ACCOUNT_IDS = os.getenv("ACCOUNT_IDS", None)


async def run():
    # Load configs and create clients
    pg_conn = await asyncpg.connect(DATABASE_URL)
    account_ids = ACCOUNT_IDS.split(",") if ACCOUNT_IDS else []
    logger.info(f"Found pre-defined accounts: {account_ids}")
    accounts = await init_accounts(pg_conn, account_ids)

    try:
        heartbeat_processor = AccountHeartbeatProcessor(accounts)
        tg_link_processors = [
            TgLinkPreProcessor(account.client) for account in accounts
        ]
        group_processors = [GroupProcessor(account.client) for account in accounts]

        all_tasks = [account.client.run_until_disconnected() for account in accounts]
        all_tasks.append(heartbeat_processor.start_processing())
        all_tasks.extend([tg_proc.start_processing() for tg_proc in tg_link_processors])
        all_tasks.extend([grp_proc.start_processing() for grp_proc in group_processors])
        async with asyncio.TaskGroup() as tg:
            running_tasks = [tg.create_task(task) for task in all_tasks]
        await asyncio.gather(*running_tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down gracefully...")
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        for account in accounts:
            await account.client.disconnect()
        await pg_conn.close()
        await redis_client.aclose()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
    finally:
        for account in accounts:
            try:
                await upload_session_file(account.tg_id)
                logger.info(f"Uploading session file for account {account.tg_id}")
            except Exception as e:
                logger.error(
                    f"Failed to upload session file for account {account.tg_id}: {e}"
                )
        logger.info("Shutdown complete")


async def init_accounts(pg_conn: asyncpg.Connection, account_ids: list[int]):
    accounts = await load_accounts(pg_conn, account_ids)

    proxies = await pick_ip_proxy(pg_conn, IpType.DATACENTER, limit=len(accounts))
    ip_usage = {proxy.ip: 0 for proxy in proxies}
    ip_usage["localhost"] = 0

    for account in accounts:
        logger.info(f"Downloading session file for account {account.tg_id}")
        session_file = await download_session_file(account.tg_id)
        if not session_file:
            logger.error(f"Failed to download session file for account {account.tg_id}")
            continue
        if ip_usage["localhost"] <= MAX_CLIENTS_PER_IP:
            account.ip = "localhost"
            logger.info(f"Running account {account.tg_id} on localhost")
            account.client = TelegramClient(
                session_file,
                account.api_id,
                account.api_hash,
            )
        else:
            proxy = await proxy_for_account(proxies, ip_usage)
            if not proxy:
                logger.error("No available proxy to run account")
                break
            account.ip = proxy.ip
            logger.info(f"Running account {account.tg_id} on proxy {proxy}")
            account.client = TelegramClient(
                session_file,
                account.api_id,
                account.api_hash,
                proxy={
                    "proxy_type": "socks5",
                    "addr": proxy.ip,
                    "port": int(proxy.port),
                    "username": proxy.username,
                    "password": proxy.password,
                    "rdns": True,
                },
                use_ipv6=False,
            )
        await account.client.start(phone=account.phone)
        ip_usage[account.ip] += 1
        await register_handlers(pg_conn, account.client)
        logger.info(f"Started Telegram client for account {account.tg_id}")
    return [acc for acc in accounts if acc.client is not None]


async def proxy_for_account(proxies: list[ProxySettings], ip_usage: dict[str, int]):
    for proxy in proxies:
        if ip_usage[proxy.ip] <= MAX_CLIENTS_PER_IP:
            return proxy
    return None


async def register_handlers(pg_conn: asyncpg.Connection, client: TelegramClient):
    me = await client.get_me()
    logger.info(f"Updating account metadata for {me.id}")
    await pg_conn.execute(
        """
        UPDATE accounts
        SET username = $1, fullname = $2, last_active_at = CURRENT_TIMESTAMP
        WHERE tg_id = $3
        """,
        me.username,
        me.first_name + f" {me.last_name}" if me.last_name else me.first_name,
        str(me.id),
    )

    logger.info(f"Registering handlers for account {me.id}")

    @client.on(events.NewMessage)
    async def handle_new_message(event: events.NewMessage):
        raw_message = event.message
        if not raw_message.is_group or not raw_message.is_channel:
            return

        msg = to_chat_message(raw_message)
        if not msg:
            return

        if await redis_client.exists(message_seen_key(msg.chat_id, msg.message_id)):
            return

        pipeline = redis_client.pipeline()
        pipeline.incr(chat_per_hour_stats_key(msg.chat_id, "messages_count"))
        pipeline.set(message_seen_key(msg.chat_id, msg.message_id), "true")
        pipeline.lpush(MESSAGE_QUEUE_KEY, msg.model_dump_json())
        await pipeline.execute()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
