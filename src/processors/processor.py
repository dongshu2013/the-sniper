import asyncio
import logging

logger = logging.getLogger(__name__)


class ProcessorBase:
    def __init__(self, interval: int):
        self.running = False
        self.interval = interval

    async def start_processing(self):
        self.running = True
        while self.running:
            try:
                await self.process()
            except Exception as e:
                logger.error(f"Failed to process: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    def stop_processing(self):
        self.running = False

    async def process(self):
        raise NotImplementedError("Process method must be implemented")
