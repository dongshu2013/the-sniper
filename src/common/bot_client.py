import logging

from telethon import TelegramClient

from .config import API_HASH, API_ID, PHONE, SESSION_NAME

logger = logging.getLogger(__name__)


class TelegramListener:
    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    async def start(self):
        await self.client.start(phone=PHONE)

    async def stop(self):
        await self.client.disconnect()
