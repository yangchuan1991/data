import scrapy


class CompanyItem(scrapy.Item):
    url = scrapy.Field()
    title = scrapy.Field()
    summary = scrapy.Field()
    links = scrapy.Field()
    company_name = scrapy.Field()
    contact_name = scrapy.Field()
    phone = scrapy.Field()
    email = scrapy.Field()
    address = scrapy.Field()
    industry = scrapy.Field()
    region = scrapy.Field()
    raw_text = scrapy.Field()
    engine = scrapy.Field()
    status = scrapy.Field()
