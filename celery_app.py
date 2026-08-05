import os
from celery import Celery

broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery("crm_crawler", broker=broker_url, backend=result_backend)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="crm_crawler.enqueue_crawl")
def enqueue_crawl(urls, db_path=None, engine="standard"):
    import os

    from app import DatabaseStore, crawl_urls_once

    resolved_db_path = db_path or os.environ.get("CRM_DB_PATH", os.path.join(os.getcwd(), "data.db"))
    store = DatabaseStore(resolved_db_path)
    store.init_db()
    return crawl_urls_once(store, urls, preferred_engine=engine)
