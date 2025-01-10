import asyncio
from logging import logger


class MessageProcessor:
    def __init__(self, interval):
        self.interval = interval
        self.running = False

    async def start_processing(self):
        self.running = True
        while self.running:
            try:
                await self.process_messages()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in message processing: {e}")

    async def process_messages(self):
        """
        Implement your periodic message processing logic here
        """
        logger.info("Processing messages...")
        # Add your processing logic here

    async def stop_processing(self):
        self.running = False
