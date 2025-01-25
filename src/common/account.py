import logging
import os

import asyncpg

from src.common.r2_client import download_file, file_exists, upload_file
from src.common.types import Account, AccountStatus

logger = logging.getLogger(__name__)


async def load_accounts(
    pg_conn: asyncpg.Connection, account_ids: list[int] | None = None
) -> list[Account]:
    """Load accounts from database."""
    select_query = """
        SELECT id, tg_id, api_id, api_hash, phone, status, last_active_at
        FROM accounts
        WHERE status = 'active'
    """
    if account_ids:
        select_query += " AND tg_id = ANY($1)"
        rows = await pg_conn.fetch(select_query, account_ids)
    else:
        rows = await pg_conn.fetch(select_query)
    return [
        Account(
            id=row["id"],
            tg_id=row["tg_id"],
            api_id=row["api_id"],
            api_hash=row["api_hash"],
            phone=row["phone"],
            status=AccountStatus(row["status"]),
            last_active_at=(
                int(row["last_active_at"].timestamp()) if row["last_active_at"] else 0
            ),
        )
        for row in rows
    ]


async def update_account_status(
    pg_conn: asyncpg.Connection,
    status: AccountStatus,
    account_ids: list[int] | None = None,
):
    await pg_conn.execute(
        """
        UPDATE accounts SET status = $1 WHERE id = ANY($2)
        """,
        status.value,
        account_ids,
    )


async def reset_account_status(pg_conn: asyncpg.Connection):
    await pg_conn.execute(
        """
        UPDATE accounts SET status = $1 WHERE status = $2
        """,
        AccountStatus.ACTIVE.value,
        AccountStatus.RUNNING.value,
    )


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


async def upload_session_file(account_id: int, session_file: str | None = None):
    session_key = gen_session_file_key(account_id)
    if not session_file:
        session_file = gen_session_file_path(account_id)

    if not os.path.exists(session_file):
        logger.error(f"Session file {session_file} does not exist")
        return

    try:
        upload_file(session_file, session_key)
    except Exception as e:
        logger.error(f"Failed to upload session file {session_file}: {e}")
        raise


def session_file_exists(account_id: int) -> bool:
    session_key = gen_session_file_key(account_id)
    return file_exists(session_key)


async def heartbeat(pg_conn: asyncpg.Connection, account: Account):
    await pg_conn.execute(
        """
        UPDATE accounts SET last_active_at = NOW(), status = $1 WHERE id = $2
        """,
        AccountStatus.RUNNING,
        account.id,
    )
