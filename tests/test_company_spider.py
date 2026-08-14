import unittest

from scrapy.http import HtmlResponse

from scrapy_project.crawler.spiders.company_spider import CompanySpider


class CompanySpiderExtractionTests(unittest.TestCase):
    def test_spider_uses_richer_profile_extraction(self):
        spider = CompanySpider(urls=["https://example.com"])
        html = """
        <html>
          <head>
            <title>智链科技</title>
            <meta property="og:site_name" content="智链科技" />
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "智链科技",
                "telephone": "+86-13800000000",
                "email": "contact@zhilian.com",
                "address": {
                  "streetAddress": "北京市朝阳区望京SOHO",
                  "addressRegion": "北京"
                },
                "industry": "人工智能"
              }
            </script>
          </head>
          <body>
            <h1>智链科技</h1>
            <p>联系人：张先生</p>
            <p>联系电话：13800000000</p>
            <p>电子邮箱：zhang@example.com</p>
            <p>公司地址：北京市朝阳区望京SOHO</p>
            <p>主营业务：人工智能</p>
          </body>
        </html>
        """
        response = HtmlResponse(url="https://example.com", body=html.encode("utf-8"), encoding="utf-8")

        items = list(spider.parse(response))

        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual("智链科技", item["company_name"])
        self.assertEqual("张先生", item["contact_name"])
        self.assertEqual("13800000000", item["phone"])
        self.assertEqual("contact@zhilian.com", item["email"])
        self.assertEqual("北京市朝阳区望京SOHO", item["address"])
        self.assertEqual("人工智能", item["industry"])
        self.assertEqual("北京", item["region"])
