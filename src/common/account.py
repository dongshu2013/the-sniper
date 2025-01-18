import logging
import os

import asyncpg

from src.common.r2_client import download_file, upload_file
from src.common.types import Account, AccountStatus

logger = logging.getLogger(__name__)


async def load_accounts(
    pg_conn: asyncpg.Connection, account_ids: list[int]
) -> list[Account]:
    """Load accounts from database."""
    rows = await pg_conn.fetch(
        """
        SELECT id, tg_id, api_id, api_hash, phone, status, last_active_at
        FROM accounts
        WHERE tg_id = ANY($1)
        """,
        account_ids,
    )
    return [
        Account(
            id=row["id"],
            tg_id=row["tg_id"],
            api_id=row["api_id"],
            api_hash=row["api_hash"],
            phone=row["phone"],
            status=AccountStatus(row["status"]),
            last_active_at=(
                int(row["last_active_at"].timestamp())
                if row["last_active_at"]
                else None
            ),
            client=None,
        )
        for row in rows
    ]


def gen_session_file_key(account_id: int):
    return f"tg-user-sessions/{account_id}.session"


def gen_session_file_path(account_id: int):
    return f"sessions/{account_id}.session"


async def download_session_file(account_id: int):
    session_key = gen_session_file_key(account_id)
    local_path = gen_session_file_path(account_id)

    os.makedirs("sessions", exist_ok=True)
    if os.path.exists(local_path):
        os.remove(local_path)

    try:
        logger.info(f"Downloading session file for account {account_id}")
        download_file(session_key, local_path)
    except Exception as e:
        logger.error(f"Error downloading session file: {e}", exc_info=True)
        return None

    return local_path


async def upload_session_file(account_id: int):
    session_key = gen_session_file_key(account_id)
    session_file = gen_session_file_path(account_id)

    try:
        upload_file(session_file, session_key)
    except Exception as e:
        logger.error(f"Failed to upload session file {session_file}: {e}")
        raise


async def heartbeat(pg_conn: asyncpg.Connection, account: Account):
    await pg_conn.execute(
        """
        UPDATE accounts SET last_active_at = NOW() WHERE id = $1
        """,
        account.id,
    )
