import logging

from telethon import TelegramClient

from .config import API_HASH, API_ID, PHONE

logger = logging.getLogger(__name__)


class TelegramListener:
    def __init__(self):
        self.client = TelegramClient("bot_session", API_ID, API_HASH)

    async def start(self):
        await self.client.start(phone=PHONE)
        logger.info("Telegram bot started successfully")

    async def stop(self):
        await self.client.disconnect()
        logger.info("Telegram bot stopped")
