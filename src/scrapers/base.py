from abc import ABC, abstractmethod

class BaseSpider(ABC):
    """Base spider class that all spiders should inherit from."""
    
    @abstractmethod
    async def crawl(self):
        """Main crawl method that should be implemented by all spiders."""
        pass

    @abstractmethod
    async def process_item(self, item):
        """Process crawled items."""
        pass

    async def start(self):
        """Start the spider."""
        try:
            await self.crawl()
        except Exception as e:
            self.logger.error(f"Error during crawl: {e}") 