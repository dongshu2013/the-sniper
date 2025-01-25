import asyncio
import logging

import asyncpg
from redis.asyncio import Redis
from telethon import TelegramClient, events
from telethon.tl.types import Message

from src.common.account import (
    download_session_file,
    load_accounts,
    reset_account_status,
    update_account_status,
)
from src.common.config import (
    DATABASE_URL,
    MESSAGE_QUEUE_KEY,
    REDIS_URL,
    chat_per_hour_stats_key,
    message_seen_key,
)
from src.common.types import Account, AccountStatus, IpType, ProxySettings
from src.helpers.ip_proxy_helper import MAX_CLIENTS_PER_IP, pick_ip_proxy
from src.helpers.message_helper import to_chat_message
from src.processors.account_heartbeat import AccountHeartbeatProcessor
from src.processors.group_processor import GroupProcessor
from src.processors.tg_link_pre_processor import TgLinkPreProcessor

# Create logger instance
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = Redis.from_url(REDIS_URL)


async def run():
    # Load configs and create clients
    pg_conn = await asyncpg.connect(DATABASE_URL)
    hb_task = None
    accounts = []
    try:
        heartbeat_processor = AccountHeartbeatProcessor([])

        async def check_new_accounts(task_group):
            while True:
                new_accounts = await load_accounts(pg_conn)
                if new_accounts:
                    new_accounts = await init_accounts(pg_conn, new_accounts)
                    for account in new_accounts:
                        tg_link_proc = TgLinkPreProcessor(account.client)
                        group_proc = GroupProcessor(account.client)
                        task_group.create_task(account.client.run_until_disconnected())
                        task_group.create_task(tg_link_proc.start_processing())
                        task_group.create_task(group_proc.start_processing())
                    await heartbeat_processor.add_accounts(new_accounts)
                    await update_account_status(
                        pg_conn, AccountStatus.RUNNING, [acc.id for acc in new_accounts]
                    )
                    accounts.extend(new_accounts)
                await asyncio.sleep(60)  # Check every minute

        async with asyncio.TaskGroup() as tg:
            hb_task = tg.create_task(heartbeat_processor.start_processing())
            tg.create_task(check_new_accounts(tg))
            await asyncio.wait_for(asyncio.Future(), timeout=None)  # Run indefinitely
    finally:
        logger.info("Shutting down gracefully...")
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        if hb_task:  # Check if task exists
            hb_task.cancel()  # Remove await
        for account in accounts:
            await account.client.disconnect()
        await reset_account_status(pg_conn)
        await pg_conn.close()
        await redis_client.aclose()


async def init_accounts(pg_conn: asyncpg.Connection, accounts: list[Account]):
    try:
        proxies = await pick_ip_proxy(pg_conn, IpType.DATACENTER, limit=len(accounts))
        ip_usage = {proxy.ip: 0 for proxy in proxies}
        ip_usage["localhost"] = 0
    except Exception as e:
        logger.error(f"Failed to pick IP proxy: {e}")
        return []

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
        raw_message: Message = event.message
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

    @client.on(events.MessageEdited)
    async def handle_message_reactions(event):
        message: Message = event.message
        msg = to_chat_message(message)
        if not msg:
            return
        await redis_client.lpush(MESSAGE_QUEUE_KEY, msg.model_dump_json())


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
