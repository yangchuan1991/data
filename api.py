import os
import sys
import threading
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import (
    DEFAULT_BEIJING_TARGET_CANDIDATES,
    DatabaseStore,
    crawl_urls_once,
    discover_viable_targets,
    normalize_urls,
    start_background_crawler,
)


class CrawlRequest(BaseModel):
    urls: List[str]
    engine: str = "standard"
    required_region: str = "北京"
    strict_region: bool = True


class CrawlResponse(BaseModel):
    status: str
    queued: int
    message: str


class DiscoverRequest(BaseModel):
    candidates: List[str] = Field(default_factory=list)
    required_region: str = "北京"
    strict_region: bool = True
    min_score: int = 4
    crawl_after_discovery: bool = True
    engine: str = "standard"


class RevivePausedRequest(BaseModel):
    required_region: str = "北京"
    strict_region: bool = True
    min_score: int = 4
    limit: int = 30


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
_BACKGROUND_CRAWLER_STATE = {}


def _should_start_background_crawler(auto_start=True):
    if os.environ.get("CRM_DISABLE_BACKGROUND_CRAWLER", "").lower() in {"1", "true", "yes", "on"}:
        return False
    if not auto_start:
        return False
    if "pytest" in sys.modules:
        return False
    return True


def _ensure_background_crawler_running(store, urls=None, interval_seconds=30, auto_start=True):
    if not _should_start_background_crawler(auto_start=auto_start):
        return None, None

    store.init_db()
    state_key = getattr(store, "db_path", str(store))
    state = _BACKGROUND_CRAWLER_STATE.get(state_key)
    if state and state["thread"].is_alive():
        return state["thread"], state["stop_event"]

    stop_event = threading.Event()
    thread, stop_event = start_background_crawler(
        store,
        urls=urls,
        interval_seconds=interval_seconds,
        stop_event=stop_event,
    )
    _BACKGROUND_CRAWLER_STATE[state_key] = {"thread": thread, "stop_event": stop_event}
    return thread, stop_event


def create_app(db_path: Optional[str] = None) -> FastAPI:
    resolved_db_path = db_path or os.environ.get("CRM_DB_PATH")
    store = DatabaseStore(resolved_db_path)
    store.init_db()
    _ensure_background_crawler_running(store, interval_seconds=30, auto_start=not bool(os.environ.get("PYTEST_CURRENT_TEST")))

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
        _ensure_background_crawler_running(store, urls=urls, interval_seconds=30)
        summary = crawl_urls_once(
            store,
            urls,
            preferred_engine=payload.engine,
            required_region=payload.required_region,
            strict_region=payload.strict_region,
        )
        monitoring.add_event(
            "crawl_submitted",
            f"processed={summary['processed']} filtered={summary['filtered']} failed={summary['failed']}",
        )
        return CrawlResponse(status="queued", queued=len(urls), message="crawl accepted")

    @app.post("/api/crawl/discover")
    def discover_targets(payload: DiscoverRequest):
        candidate_urls = normalize_urls("\n".join(payload.candidates)) if payload.candidates else list(DEFAULT_BEIJING_TARGET_CANDIDATES)
        result = discover_viable_targets(
            candidate_urls,
            required_region=payload.required_region,
            min_score=max(1, min(10, payload.min_score)),
            strict_region=payload.strict_region,
        )
        for item in result.get("viable", []):
            store.update_target_health(item["url"], "completed", score=item.get("score", 0))
        for item in result.get("rejected", []):
            status = "filtered" if "not in" in str(item.get("reason", "")) else "failed"
            store.update_target_health(item["url"], status, score=item.get("score", 0), error=item.get("reason"))
        viable_urls = [item["url"] for item in result.get("viable", [])]
        crawl_summary = None
        if viable_urls:
            store.append_crawl_targets(viable_urls)
            if payload.crawl_after_discovery:
                crawl_summary = crawl_urls_once(
                    store,
                    viable_urls,
                    preferred_engine=payload.engine,
                    required_region=payload.required_region,
                    strict_region=payload.strict_region,
                )
        monitoring.add_event(
            "crawl_discovery",
            f"total={result['total']} viable={len(viable_urls)} rejected={len(result['rejected'])}",
        )
        return {
            "status": "ok",
            "total": result["total"],
            "viable": result["viable"],
            "rejected": result["rejected"],
            "appended": len(viable_urls),
            "crawl_summary": crawl_summary,
        }

    @app.post("/api/crawl/prune-paused")
    def prune_paused_targets():
        removed = store.prune_paused_targets()
        monitoring.add_event("crawl_prune_paused", f"removed={len(removed)}")
        return {"status": "ok", "removed": len(removed), "urls": removed}

    @app.post("/api/crawl/revive-paused")
    def revive_paused_targets(payload: RevivePausedRequest):
        result = store.revive_paused_targets(
            required_region=payload.required_region,
            min_score=max(1, min(10, payload.min_score)),
            strict_region=payload.strict_region,
            limit=max(1, min(200, payload.limit)),
        )
        monitoring.add_event("crawl_revive_paused", f"total={result['total']} revived={result['revived']} rejected={result['rejected']}")
        return {"status": "ok", **result}

    return app


app = create_app()
