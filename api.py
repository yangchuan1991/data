import os
import threading
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import DatabaseStore, crawl_urls_once


class CrawlRequest(BaseModel):
    urls: List[str]
    engine: str = "standard"


class CrawlResponse(BaseModel):
    status: str
    queued: int
    message: str


class MonitoringService:
    def __init__(self):
        self._lock = threading.Lock()
        self._events = []

    def add_event(self, name: str, details: str):
        with self._lock:
            self._events.append({"name": name, "details": details})
            if len(self._events) > 100:
                self._events = self._events[-100:]

    def list_events(self):
        with self._lock:
            return list(self._events)


monitoring = MonitoringService()


def create_app(db_path: Optional[str] = None) -> FastAPI:
    resolved_db_path = db_path or os.environ.get("CRM_DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))
    store = DatabaseStore(resolved_db_path)
    store.init_db()

    app = FastAPI(title="CRM Crawler API", version="1.0.0")

    @app.get("/healthz")
    def healthz():
        monitoring.add_event("healthz", "ok")
        return {"status": "ok", "database": resolved_db_path}

    @app.get("/metrics")
    def metrics():
        summary = store.get_dashboard_summary()
        payload = [
            f"crm_leads_total {summary['lead_count']}",
            f"crm_campaigns_total {summary['campaign_count']}",
            f"crm_messages_total {summary['message_count']}",
            f"crm_crawl_jobs_total {summary['crawl_count']}",
        ]
        return {"metrics": payload, "events": monitoring.list_events()}

    @app.post("/api/crawl", response_model=CrawlResponse)
    def submit_crawl(payload: CrawlRequest):
        if not payload.urls:
            raise HTTPException(status_code=400, detail="urls cannot be empty")
        urls = [item.strip() for item in payload.urls if item and item.strip()]
        store.save_crawl_targets(urls)
        summary = crawl_urls_once(store, urls, preferred_engine=payload.engine)
        monitoring.add_event("crawl_submitted", f"processed={summary['processed']} failed={summary['failed']}")
        return CrawlResponse(status="queued", queued=len(urls), message="crawl accepted")

    return app


app = create_app()
