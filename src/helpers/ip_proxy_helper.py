from typing import Optional

import asyncpg

from src.common.types import IpType, ProxySettings

MAX_CLIENTS_PER_IP = 10


async def pick_ip_proxy(
    pg_conn: asyncpg.Connection,
    ip_type: IpType,
    region: Optional[str] = None,
    limit: int = 1,
) -> ProxySettings:
    select_query = """
    SELECT ip, port, username, password
    FROM ip_pool
    WHERE type = $1
    AND expired_at > NOW() + INTERVAL '7 days'
    AND ($2::text IS NULL OR region = $2)
    AND running_accounts < $3
    LIMIT $4
    """
    rows = await pg_conn.fetch(
        select_query, ip_type.value, region, MAX_CLIENTS_PER_IP, limit
    )
    if not rows:
        raise Exception("No available proxy")
    return [
        ProxySettings(
            ip=row["ip"],
            port=row["port"],
            username=row["username"],
            password=row["password"],
        )
        for row in rows
    ]
