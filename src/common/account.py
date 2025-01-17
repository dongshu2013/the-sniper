import os

import asyncpg
import boto3

from src.common.types import Account

R2_ENDPOINT = f"https://{os.environ.get('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "the-sniper")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
s3 = boto3.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)


async def load_accounts(
    pg_conn: asyncpg.Connection, account_ids: list[int]
) -> list[Account]:
    accounts = await pg_conn.fetch(
        """
        SELECT id, api_id, api_hash, phone, last_active_at
        FROM accounts
        WHERE status = 'active' and id in ($1)
        """,
        account_ids,
    )
    return [Account.model_validate(account) for account in accounts]


def gen_session_file_key(account_id: int):
    return f"the-sniper/tg-user-sessions/{account_id}.session"


def gen_session_file_path(account_id: int):
    return f"sessions/{account_id}.session"


async def download_session_file(account_id: int):
    session_key = gen_session_file_key(account_id)
    local_path = gen_session_file_path(account_id)

    os.makedirs("sessions", exist_ok=True)
    if os.path.exists(local_path):
        os.remove(local_path)

    try:
        s3.download_file(R2_BUCKET_NAME, session_key, local_path)
    except Exception as e:
        print(f"Error downloading session file: {e}")
        return None

    return local_path


async def upload_session_file(account_id: int):
    session_key = gen_session_file_key(account_id)
    session_file = gen_session_file_path(account_id)
    s3.upload_file(R2_BUCKET_NAME, session_key, session_file)


async def heartbeat(pg_conn: asyncpg.Connection, account: Account):
    await pg_conn.execute(
        """
        UPDATE accounts SET last_active_at = NOW() WHERE id = $1
        """,
        account.id,
    )
