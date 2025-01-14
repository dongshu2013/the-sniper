import random
import logging
from playwright.async_api import async_playwright
from scrapy.selector import Selector

from ..base import BaseSpider
from .items import ChatMetadata
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
        last_height = await page.evaluate('document.body.scrollHeight')
        max_attempts = 30  # 设置最大尝试次数
        attempts = 0
        
        while attempts < max_attempts:
            # 1. 等待新内容加载
            await page.wait_for_selector("div.g-table-row", timeout=5000)
            
            # 2. 获取当前可见的所有行
            rows = await page.query_selector_all("div.g-table-row")
            current_count = len(rows)
            
            # 3. 滚动并等待新内容
            scroll_distance = random.randint(300, 700) 
            await page.evaluate(f'window.scrollBy(0, {scroll_distance})')
            await page.wait_for_timeout(random.randint(1000, 2000))
            
            # 4. 检查是否有新内容加载
            new_rows = await page.query_selector_all("div.g-table-row")
            if len(new_rows) == current_count:
                # 再次确认是否真的到底
                await page.wait_for_timeout(2000)
                final_rows = await page.query_selector_all("div.g-table-row")
                if len(final_rows) == current_count:
                    break
                    
            attempts += 1
            
    async def _parse_content(self, content):
        items = []
        selector = Selector(text=content)
        
        # 使用更精确的XPath选择器
        meme_cards = selector.xpath("//div[contains(@class, 'g-table-row') and contains(@class, 'cursor-pointer') and not(contains(@style, 'display: none'))]")
        
        self.logger.info(f"Found {len(meme_cards)} meme cards")
        
        for meme in meme_cards:
            try:
                # Get all social links
                tg_account = meme.xpath(".//a[@aria-label='telegram']/@href").get()
                x_account = meme.xpath(".//a[@aria-label='twitter']/@href").get()
                website = meme.xpath(".//a[@aria-label='website']/@href").get()
                
                # Skip if no social links
                if not (tg_account or x_account or website):
                    continue
                    
                item = ChatMetadata()
                
                # Set basic fields
                item.category = "meme_project"
                item.tme_link = tg_account
                item.twitter = x_account
                item.website = website
                item.source_link = self.start_urls[0]  # gmgn.ai URL
                
                # Build entity dictionary
                ticker = meme.xpath(".//div[@title]/@title").get()
                address = meme.xpath(".//a[contains(@href, '/token/')]/@href").extract_first()
                if address:
                    # Extract token address from URL path
                    address = address.split('/token/')[-1]
                    
                chain_img = meme.xpath("//div[starts-with(@id, 'menu-button-')]//img[@alt='network']/@src").get()
                chain = chain_img.split('/')[-1].split('.')[0] if chain_img else None
                
                item.entity = {
                    'chain': chain,
                    'address': address,
                    'ticker': ticker
                }
                
                if not ticker:
                    self.logger.warning(f"Skipping item due to missing ticker: {item}")
                    continue
                    
                items.append(item)
                
            except Exception as e:
                self.logger.error(f"Error processing meme card: {str(e)}")
                continue
                
        return items
        
    async def process_item(self, item):
        await self.pipeline.process_item(item) 