import os
import re
import sys
import scrapy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from crawler.items import CompanyItem


class CompanySpider(scrapy.Spider):
    name = "company_spider"
    allowed_domains = []
    start_urls = []

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "CONCURRENT_REQUESTS": 1,
    }

    def __init__(self, urls=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_path = kwargs.get("db_path") or os.getenv("CRAWLER_DB_PATH", "data.db")
        target_urls = urls or kwargs.get("urls") or os.getenv("CRAWLER_URLS", "")
        if isinstance(target_urls, str):
            self.start_urls = [u.strip() for u in target_urls.split(",") if u.strip()]
        else:
            self.start_urls = [str(u).strip() for u in target_urls if str(u).strip()]
        if not self.start_urls:
            self.start_urls = ["https://example.com"]
        self.allowed_domains = list({self._domain_from_url(u) for u in self.start_urls if self._domain_from_url(u)})

    def _domain_from_url(self, url):
        match = re.match(r"https?://([^/]+)", url)
        return match.group(1) if match else None

    def parse(self, response):
        text = " ".join(response.css("::text").getall())
        title = response.css("title::text").get(default="")
        summary = re.sub(r"\s+", " ", text[:500]).strip()
        links = [response.urljoin(link) for link in response.css("a::attr(href)").getall() if link]
        item = CompanyItem()
        item["url"] = response.url
        item["title"] = (title or "").strip()
        item["summary"] = summary
        item["links"] = links
        item["company_name"] = self._extract_company_name(response, text)
        item["contact_name"] = None
        item["phone"] = self._extract_phone(text)
        item["email"] = self._extract_email(text)
        item["address"] = None
        item["industry"] = None
        item["region"] = "北京"
        item["raw_text"] = text
        item["engine"] = "scrapy"
        item["status"] = "new"
        yield item

    def _extract_company_name(self, response, text):
        title = response.css("title::text").get(default="")
        if title:
            return title.strip()
        return text[:120].strip()

    def _extract_phone(self, text):
        match = re.search(r"(1[3-9]\d{9}|\d{3,4}[-－]?\d{7,8})", text)
        return match.group(1) if match else None

    def _extract_email(self, text):
        match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
        return match.group(1) if match else None
