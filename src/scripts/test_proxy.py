import asyncio

import asyncpg
from aiohttp import ClientSession, TCPConnector
from async_timeout import timeout

from src.common.config import DATABASE_URL
from src.common.types import IpType
from src.helpers.ip_proxy_helper import pick_ip_proxy


async def print_proxy_details():
    conn = await asyncpg.connect(DATABASE_URL)
    proxies = await pick_ip_proxy(conn, IpType.DATACENTER)
    proxy = proxies[0]
    print("\nProxy details:")
    print(f"IP: {proxy.ip}")
    print(f"Port: {proxy.port}")
    print(f"Username: {proxy.username}")
    print(f"Password: {proxy.password}")
    curl_cmd = (
        f"curl --socks5 {proxy.ip}:{proxy.port} "
        f"-U {proxy.username}:{proxy.password} -v https://telegram.org"
    )
    print("\nCurl command:")
    print(curl_cmd)

    proxy_url = (
        f"socks5://{proxy.username}:{proxy.password}" f"@{proxy.ip}:{proxy.port}"
    )
    async with timeout(10):
        connector = TCPConnector(ssl=False)
        async with ClientSession(connector=connector) as session:
            async with session.get("https://telegram.org", proxy=proxy_url) as response:
                print(f"Status: {response.status}")
                print(f"Working: {response.status == 200}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(print_proxy_details())
