from logging import logger

from telethon import TelegramClient

from .config import API_HASH, API_ID, BOT_TOKEN


class TelegramListener:
    def __init__(self):
        self.client = TelegramClient("bot_session", API_ID, API_HASH)

    async def start(self):
        await self.client.start(bot_token=BOT_TOKEN)
        logger.info("Telegram bot started successfully")

    async def stop(self):
        await self.client.disconnect()
        logger.info("Telegram bot stopped")
