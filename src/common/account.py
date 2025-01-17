import logging
import os

import asyncpg
import boto3
from botocore.config import Config

from src.common.config import (
    R2_ACCESS_KEY_ID,
    R2_BUCKET_NAME,
    R2_ENDPOINT,
    R2_SECRET_ACCESS_KEY,
)
from src.common.types import Account, AccountStatus

# Create the client
s3 = boto3.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(
        s3={"addressing_style": "virtual"},
        signature_version="s3v4",
        retries={"max_attempts": 3},
    ),
)

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
        s3.download_file(R2_BUCKET_NAME, session_key, local_path)
    except Exception as e:
        logger.error(f"Error downloading session file: {e}", exc_info=True)
        return None

    return local_path


async def upload_session_file(account_id: int):
    session_key = gen_session_file_key(account_id)
    session_file = gen_session_file_path(account_id)

    try:
        s3.upload_file(session_file, R2_BUCKET_NAME, session_key)
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
