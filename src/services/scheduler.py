import asyncio
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncpg

from src.common.config import DATABASE_URL, ENV
from src.processors.gmgn_crawler import MemeCrawler

logger = logging.getLogger(__name__)

class CrawlerScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.pg_conn = None
        
    async def setup(self):
        """设置数据库连接和爬虫实例"""
        self.pg_conn = await asyncpg.connect(DATABASE_URL)
        self.crawler = MemeCrawler(self.pg_conn)
        
    async def cleanup(self):
        """清理资源"""
        if self.pg_conn:
            await self.pg_conn.close()
            
    async def crawl_task(self):
        """执行爬虫任务"""
        try:
            logger.info(f"Starting scheduled crawl at {datetime.now()}")
            await self.crawler.process_meme_data()
            logger.info(f"Completed scheduled crawl at {datetime.now()}")
        except Exception as e:
            logger.error(f"Error in scheduled crawl: {e}")
            
    def start(self):
        """启动调度器"""
        if ENV == "development":
            # 开发环境：每分钟执行一次
            self.scheduler.add_job(
                self.crawl_task,
                'interval',
                minutes=1,
                id='meme_crawler_dev',
                replace_existing=True
            )
            logger.info("Development mode: Crawler will run every minute")
        else:
            # 生产环境：保持原有的每小时和每天的调度
            self.scheduler.add_job(
                self.crawl_task,
                CronTrigger(minute=0),  # 每小时整点执行
                id='meme_crawler',
                replace_existing=True
            )
            
            self.scheduler.add_job(
                self.crawl_task,
                CronTrigger(hour=3, minute=0),  # 每天凌晨3点执行
                id='meme_crawler_full_sync',
                replace_existing=True
            )
            logger.info("Production mode: Crawler will run hourly and daily at 3 AM")
        
        self.scheduler.start()
        logger.info("Crawler scheduler started")

async def run_scheduler():
    scheduler = CrawlerScheduler()
    try:
        await scheduler.setup()
        scheduler.start()
        
        # 保持程序运行
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
    finally:
        await scheduler.cleanup()
        
def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(run_scheduler())

if __name__ == "__main__":
    main() 