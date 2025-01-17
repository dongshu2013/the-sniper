import logging

import asyncpg

from src.common.account import heartbeat
from src.common.config import DATABASE_URL
from src.common.types import Account
from src.processors.processor import ProcessorBase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class AccountHeartbeatProcessor(ProcessorBase):
    def __init__(
        self,
        accounts: list[Account],
        interval: int = 60,  # every 60 seconds
    ):
        super().__init__(interval=interval)
        self.pg_conn = None
        self.accounts = accounts

    async def process(self) -> int:
        if not self.pg_conn:
            self.pg_conn = await asyncpg.connect(DATABASE_URL)

        for account in self.accounts:
            await heartbeat(self.pg_conn, account)
