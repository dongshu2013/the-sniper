import asyncio
import logging

from src.scrapers.gmgn.spider import GmgnSpider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_spider(spider_name: str):
    """Run specified spider"""
    spiders = {
        "gmgn": GmgnSpider
    }
    
    if spider_name not in spiders:
        raise ValueError(f"Spider {spider_name} not found. Available spiders: {list(spiders.keys())}")
    
    spider_class = spiders[spider_name]
    spider = spider_class()
    
    try:
        logger.info(f"Starting spider: {spider_name}")
        await spider.start()
        logger.info(f"Spider {spider_name} finished successfully")
    except Exception as e:
        logger.error(f"Error running spider {spider_name}: {e}")
        raise

def main():
    """Entry point for running spiders"""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.scrapers.runner <spider_name>")
        print("Available spiders: gmgn")
        sys.exit(1)
        
    spider_name = sys.argv[1]
    asyncio.run(run_spider(spider_name))

if __name__ == "__main__":
    main() 