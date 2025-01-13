import random
import logging
from playwright.async_api import async_playwright
from scrapy.selector import Selector

from ..base import BaseSpider
from .items import GmgnItem
from .pipeline import PostgresPipeline
from ..config import PLAYWRIGHT_CONFIG, DOWNLOAD_DELAY

class GmgnSpider(BaseSpider):
    name = "gmgn"
    start_urls = ["https://gmgn.ai/?chain=sol"]
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.pipeline = PostgresPipeline()
        
    async def crawl(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(**PLAYWRIGHT_CONFIG['launch_options'])
            
            context = await browser.new_context(**PLAYWRIGHT_CONFIG['context_options'])
            
            page = await context.new_page()
            
            for url in self.start_urls:
                try:
                    await page.goto(url)
                    await self._scroll_page(page)
                    content = await page.content()
                    items = await self._parse_content(content)
                    for item in items:
                        await self.process_item(item)
                        delay = DOWNLOAD_DELAY + random.uniform(-2, 2)
                        await page.wait_for_timeout(delay * 1000)
                except Exception as e:
                    self.logger.error(f"Error crawling {url}: {e}")
                    
            await browser.close()
            
    async def _scroll_page(self, page):
        # 移植原有的滚动逻辑
        last_height = await page.evaluate('document.body.scrollHeight')
        while True:
            scroll_distance = random.randint(300, 700)
            await page.evaluate(f'window.scrollBy(0, {scroll_distance})')
            await page.wait_for_timeout(random.randint(500, 1500))
            new_height = await page.evaluate('document.body.scrollHeight')
            if new_height == last_height:
                break
            last_height = new_height
            
    async def _parse_content(self, content):
        items = []
        selector = Selector(text=content)
        meme_cards = selector.xpath("//div[contains(@class, 'g-table-row') and contains(@class, 'cursor-pointer')]")
        
        self.logger.info(f"Found {len(meme_cards)} meme cards")
        
        for meme in meme_cards:
            try:
                tg_account = meme.xpath(".//a[@aria-label='telegram']/@href").get()
                if not tg_account or not tg_account.startswith("https://t.me/"):
                    continue
                    
                item = GmgnItem()
                item.ticker = meme.xpath(".//div[@title]/@title").get()
                item.x_account = meme.xpath(".//a[@aria-label='twitter']/@href").get()
                item.website = meme.xpath(".//a[@aria-label='website']/@href").get()
                item.tg_account = tg_account
                item.source = "gmgn"
                
                if not item.ticker:
                    self.logger.warning(f"Skipping item due to missing ticker: {item}")
                    continue
                    
                items.append(item)
                
            except Exception as e:
                self.logger.error(f"Error processing meme card: {str(e)}")
                continue
                
        return items
        
    async def process_item(self, item):
        await self.pipeline.process_item(item) 