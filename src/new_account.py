import argparse
import asyncio
import logging

import asyncpg
from telethon import TelegramClient

from src.common.account import upload_session_file
from src.common.config import DATABASE_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def create_new_account(api_id: str, api_hash: str, phone: str):
    # Initialize temporary session
    client = TelegramClient(f"NEW_SESSION_{phone}", api_id, api_hash)

    try:
        # Start the client and connect
        if phone.startswith("+"):
            await client.start(phone=phone)
        else:
            await client.start(phone=f"+{phone}")

        # Get account info
        me = await client.get_me()
        tg_id = str(me.id)
        username = me.username
        fullname = me.first_name + f" {me.last_name}" if me.last_name else me.first_name

        # Connect to database
        conn = await asyncpg.connect(DATABASE_URL)

        # Insert account data
        await conn.execute(
            """
            INSERT INTO accounts (tg_id, username, api_id, api_hash, phone, fullname)
            VALUES ($1, $2, $3, $4, $5, $6)
        """,
            tg_id,
            username,
            api_id,
            api_hash,
            phone,
            fullname,
        )

        # Upload session file
        await upload_session_file(tg_id, f"NEW_SESSION_{phone}.session")

        logger.info(f"Successfully created account for {username} (ID: {tg_id})")

    except Exception as e:
        logger.error(f"Failed to create account: {e}")
        raise
    finally:
        # Cleanup
        await client.disconnect()
        if "conn" in locals():
            await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Create a new Telegram account entry")
    parser.add_argument("--api-id", required=True, help="Telegram API ID")
    parser.add_argument("--api-hash", required=True, help="Telegram API Hash")
    parser.add_argument(
        "--phone", required=True, help="Phone number in international format"
    )

    args = parser.parse_args()

    asyncio.run(
        create_new_account(api_id=args.api_id, api_hash=args.api_hash, phone=args.phone)
    )


if __name__ == "__main__":
    main()
