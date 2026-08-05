import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import DatabaseStore


class SQLitePipeline:
    def open_spider(self, spider):
        self.store = DatabaseStore(spider.db_path or os.getenv("CRAWLER_DB_PATH", "data.db"))
        self.store.init_db()

    def process_item(self, item, spider):
        item_dict = dict(item)
        url = item_dict.get("url") or spider.current_url
        self.store.add_crawl_job(url, item_dict.get("title", ""), item_dict.get("summary", ""), "completed")
        self.store.add_company_profile(url, item_dict)
        self.store.log_activity("scrapy_crawl_completed", f"Scrapy crawled {url}")
        return item
