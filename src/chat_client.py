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
from src.common.types import ChatMessage
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


async def run():
    # Load configs and create clients
    pg_conn = await asyncpg.connect(DATABASE_URL)
    account_ids = os.getenv("ACCOUNT_IDS").split(",")
    if not account_ids:
        logger.error("No account ids found")
        return

    accounts = await init_accounts(pg_conn, account_ids)
    heartbeat_processor = AccountHeartbeatProcessor(accounts)
    tg_link_processors = [TgLinkPreProcessor(account.client) for account in accounts]
    group_processors = [GroupProcessor(account.client) for account in accounts]

    try:
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
    for account in accounts:
        logger.info(f"Downloading session file for account {account.tg_id}")
        session_file = await download_session_file(account.tg_id)
        if not session_file:
            logger.error(f"Failed to download session file for account {account.tg_id}")
            continue
        client = TelegramClient(session_file, account.api_id, account.api_hash)
        await client.start(phone=account.phone)
        await register_handlers(pg_conn, client)
        logger.info(f"Started Telegram client for account {account.tg_id}")
        account.client = client
    return [acc for acc in accounts if acc.client is not None]


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
        message = event.message
        if not message.is_group or not message.is_channel:
            return

        chat_id = str(message.chat_id)
        if chat_id.startswith("-100"):
            chat_id = chat_id[4:]

        message_id = str(message.id)
        if await redis_client.exists(message_seen_key(chat_id, message_id)):
            return

        reply_to = None
        topic_id = None
        if message.reply_to:
            if message.reply_to.forum_topic:
                if message.reply_to.reply_to_topic_id:
                    reply_to = message.reply_to.reply_to_msg_id
                    topic_id = message.reply_to.reply_to_topic_id
                else:
                    topic_id = message.reply_to.reply_to_msg_id
            else:
                reply_to = message.reply_to.reply_to_msg_id

        message_data = ChatMessage(
            message_id=message_id,
            chat_id=chat_id,
            message_text=event.message.text,
            sender_id=str(event.sender_id),
            message_timestamp=int(event.date.timestamp()),
            reply_to=str(reply_to) if reply_to else None,
            topic_id=str(topic_id) if topic_id else None,
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
