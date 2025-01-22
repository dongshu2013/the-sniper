import asyncio
import logging

import asyncpg
import redis.asyncio as Redis
from pydantic import BaseModel
from telethon import TelegramClient

from src.common.account import upload_session_file
from src.common.config import DATABASE_URL, REDIS_URL, SERVICE_PREFIX
from src.common.types import IpType
from src.helpers.ip_proxy_helper import pick_ip_proxy
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


NEW_ACCOUNT_REQUEST_KEY = f"{SERVICE_PREFIX}:new_account_request"


def phone_code_key(phone: str) -> str:
    return f"{SERVICE_PREFIX}:phone_code:{phone}"


class NewAccountRequest(BaseModel):
    api_id: str
    api_hash: str
    phone: str


class NewAccountProcessor(ProcessorBase):
    def __init__(self):
        super().__init__(interval=1)
        self.pg_conn = None
        self.tasks = {}
        self.redis_client = Redis.from_url(REDIS_URL)

    async def process(self):
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        while True:
            request = await self.redis_client.lpop(NEW_ACCOUNT_REQUEST_KEY)
            if not request:
                break

            request = NewAccountRequest.model_validate_json(request)
            old_task = self.tasks.get(request.phone)
            if old_task:
                old_task.cancel()
            self.tasks[request.phone] = asyncio.create_task(
                self.process_request(request)
            )

    async def process_request(self, request: NewAccountRequest):
        proxy = await pick_ip_proxy(self.pg_conn, IpType.DATACENTER)
        session = request.phone.replace("+", "")
        # The socks5h protocol tells the client to perform DNS resolution
        # through the proxy server, which is often necessary for residential proxies.

        client = TelegramClient(
            session,
            request.api_id,
            request.api_hash,
            proxy={
                "proxy_type": "socks5h",
                "addr": proxy.ip,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
            },
            connection_retries=5,
            timeout=30,
        )
        try:
            await client.connect()
            phone_code = await client.send_code_request(request.phone)
            phone_code_hash = phone_code.phone_code_hash

            code = None
            for _ in range(300):  # wait for 5 minutes
                code = await self.redis_client.get(phone_code_key(request.phone))
                if code:
                    break
                await asyncio.sleep(1)  # Cancellation can happen here

            if not code:
                logger.error(f"Failed to get phone code for {request.phone}")
                return

            await client.sign_in(
                phone=request.phone, code=code, phone_code_hash=phone_code_hash
            )
            me = await client.get_me()
            tg_id = str(me.id)
            await upload_session_file(tg_id, f"{session}.session")

            username = me.username
            fullname = (
                me.first_name + f" {me.last_name}" if me.last_name else me.first_name
            )
            await self.add_new_account(
                tg_id,
                username,
                request.api_id,
                request.api_hash,
                request.phone,
                fullname,
            )
            logger.info(f"Successfully created account for {username} (ID: {tg_id})")
        except asyncio.CancelledError:
            logger.info(f"Account creation cancelled for {request.phone}")
            raise  # Re-raise the cancellation
        except Exception as e:
            logger.error(f"Error processing request for {request.phone}: {e}")
        finally:
            await client.disconnect()

    async def add_new_account(
        self,
        tg_id: str,
        username: str,
        api_id: str,
        api_hash: str,
        phone: str,
        fullname: str,
    ):
        # Insert account data
        await self.pg_conn.execute(
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
