import asyncio


class ProcessorBase:
    def __init__(self, interval: int):
        self.running = False
        self.interval = interval

    async def start_processing(self):
        self.running = True
        while self.running:
            await self.process()
            await asyncio.sleep(self.interval)

    def stop_processing(self):
        self.running = False

    async def process(self):
        raise NotImplementedError("Process method must be implemented")
