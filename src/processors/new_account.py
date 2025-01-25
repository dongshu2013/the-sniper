import asyncio
import json
import logging
import time
from typing import Optional

import asyncpg
import phonenumbers
import redis.asyncio as Redis
from pydantic import BaseModel
from telethon import TelegramClient

from src.common.account import upload_session_file
from src.common.config import (
    DATABASE_URL,
    DEFAULT_API_HASH,
    DEFAULT_API_ID,
    REDIS_URL,
    SERVICE_PREFIX,
)
from src.common.types import IpType
from src.helpers.ip_proxy_helper import pick_ip_proxy
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


NEW_ACCOUNT_REQUEST_KEY = f"{SERVICE_PREFIX}:new_account_request"
DEFAULT_TIMEOUT = 900


def phone_code_key(phone: str) -> str:
    return f"{SERVICE_PREFIX}:phone_code:{phone}"


def phone_status_key(phone: str) -> str:
    return f"{SERVICE_PREFIX}:phone_status:{phone}"


class NewAccountRequest(BaseModel):
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    phone: str


def normalize_phone(phone: str) -> str | None:
    try:
        # Parse phone number (assuming international format if no region specified)
        parsed = phonenumbers.parse(phone)

        # Check if the number is valid
        if not phonenumbers.is_valid_number(parsed):
            return None

        # Format in E.164 format (+123456789)
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        return None


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

            logger.info(f"Processing request {request}")
            try:
                request = NewAccountRequest.model_validate_json(request)
            except Exception as e:
                logger.error(f"Failed to parse request: {request}, error: {e}")
                continue

            normalized_phone = normalize_phone(request.phone)
            if not normalized_phone:
                continue

            if request.api_id is None or request.api_hash is None:
                logger.info(
                    f"API ID or API hash is provided for "
                    f"{request.phone}, will use default"
                )
                request.api_id = DEFAULT_API_ID
                request.api_hash = DEFAULT_API_HASH

            request.phone = normalized_phone
            old_task = self.tasks.get(request.phone)
            if old_task:
                old_task.cancel()
                logger.info(f"Cancelled old task for {request.phone}")
                await self.redis_client.set(
                    phone_status_key(request.phone), "cancelled", ex=DEFAULT_TIMEOUT
                )
                return

            # Wrap process_request with timeout of 15 minutes
            task = asyncio.create_task(
                asyncio.wait_for(
                    self.process_request(request), timeout=DEFAULT_TIMEOUT
                )  # 15 minutes in seconds
            )
            task.add_done_callback(
                lambda t, phone=request.phone: self._handle_task_exception(t, phone)
            )
            self.tasks[request.phone] = task

    def _handle_task_exception(self, task, phone):
        try:
            task.result()
        except Exception as e:
            logger.error(f"Task for phone {phone} failed with error: {e}")
        finally:
            # Clean up the task from self.tasks
            if phone in self.tasks and self.tasks[phone] == task:
                del self.tasks[phone]

    async def process_request(self, request: NewAccountRequest):
        try:
            if await self.account_exists(request.phone):
                logger.info(f"Account already exists for {request.phone}")
                raise Exception("Account already exists")

            proxies = await pick_ip_proxy(self.pg_conn, IpType.DATACENTER)
            proxy = proxies[0]
            session = f"{request.phone.replace('+', '')}_{int(time.time())}"
            client = TelegramClient(
                session,
                request.api_id,
                request.api_hash,
                proxy={
                    "proxy_type": "socks5",
                    "addr": proxy.ip,
                    "port": proxy.port,
                    "username": proxy.username,
                    "password": proxy.password,
                },
                connection_retries=5,
                timeout=30,
            )
        except Exception as e:
            logger.error(f"Error creating Telegram client for {request.phone}: {e}")
            await self.redis_client.set(
                phone_status_key(request.phone), "error", ex=DEFAULT_TIMEOUT
            )
            return

        status = "error"
        try:
            await client.connect()
            logger.info(f"Sending code request to {request.phone}")
            phone_code = await client.send_code_request(request.phone)
            phone_code_hash = phone_code.phone_code_hash

            logger.info(f"Waiting for code for {request.phone}")
            code = None
            for _ in range(300):  # wait for 5 minutes
                code = await self.redis_client.get(phone_code_key(request.phone))
                if code:
                    code = int(code.decode("utf-8"))
                    logger.info(f"Got phone code for {request.phone} as {code}")
                    break
                await asyncio.sleep(1)  # Cancellation can happen here

            if not code:
                logger.error(f"Failed to get phone code for {request.phone}")
                return

            logger.info(f"Signing in to {request.phone}")
            await client.sign_in(
                phone=request.phone, code=code, phone_code_hash=phone_code_hash
            )
            me = await client.get_me()
            tg_id = str(me.id)
            logger.info(f"Uploading session file for {tg_id}({request.phone})")
            await upload_session_file(tg_id, f"{session}.session")

            username = me.username
            fullname = (
                me.first_name + f" {me.last_name}" if me.last_name else me.first_name
            )
            logger.info(f"Adding new account for {username} (ID: {tg_id})")
            account_id = await self.add_new_account(
                tg_id,
                username,
                request.api_id,
                request.api_hash,
                request.phone,
                fullname,
            )
            logger.info(f"Successfully created account for {username} (ID: {tg_id})")
            status = json.dumps(
                {"status": "success", "account_id": account_id, "tg_id": tg_id}
            )
        except Exception as e:
            logger.error(f"Error processing request for {request.phone}: {e}")
            status = "error"
            raise e
        finally:
            await self.redis_client.set(
                phone_status_key(request.phone), status, ex=DEFAULT_TIMEOUT
            )
            await client.disconnect()

    async def add_new_account(
        self,
        tg_id: str,
        username: str,
        api_id: str,
        api_hash: str,
        phone: str,
        fullname: str,
    ) -> int:
        # Insert account data and return the id
        account_id = await self.pg_conn.fetchval(
            """
            INSERT INTO accounts (tg_id, username, api_id, api_hash, phone, fullname)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """,
            tg_id,
            username,
            api_id,
            api_hash,
            phone,
            fullname,
        )
        return account_id

    async def account_exists(self, phone: str) -> bool:
        count = await self.pg_conn.fetchval(
            "SELECT COUNT(*) FROM accounts WHERE phone = $1", phone
        )
        return count > 0


def main():
    asyncio.run(NewAccountProcessor().start_processing())


if __name__ == "__main__":
    main()
