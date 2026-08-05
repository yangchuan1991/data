BOT_NAME = "crm_crawler"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"
ROBOTSTXT_OBEY = False
DOWNLOAD_DELAY = 0.3
CONCURRENT_REQUESTS = 2
RETRY_TIMES = 2
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
DOWNLOAD_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; CRMCrawler/1.0; +https://example.org)"
ITEM_PIPELINES = {
    "crawler.pipelines.SQLitePipeline": 300,
}
FEED_EXPORT_ENCODING = "utf-8"
HTTPCACHE_ENABLED = False
