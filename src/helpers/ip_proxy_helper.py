from typing import Optional

import asyncpg

from src.common.types import IpType, ProxySettings


async def pick_ip_proxy(
    pg_conn: asyncpg.Connection, ip_type: IpType, region: Optional[str] = None
) -> ProxySettings:
    select_query = """
    SELECT ip, port, username, password
    FROM ip_pool
    WHERE type = $1
    AND expired_at > NOW()
    AND ($2::text IS NULL OR region = $2)
    LIMIT 1
    """
    row = await pg_conn.fetchrow(select_query, ip_type.value, region)
    if not row:
        raise Exception("No available proxy")
    return ProxySettings(
        ip=row["ip"],
        port=row["port"],
        username=row["username"],
        password=row["password"],
    )
