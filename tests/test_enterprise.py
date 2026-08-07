import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from api import create_app


class EnterpriseApiTests(unittest.TestCase):
    def setUp(self):
        os.environ["CRM_POSTGRES_DSN"] = "postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local"
        self.db_path = None
        os.environ.pop("CRM_DB_PATH", None)
        from app import DatabaseStore

        store = DatabaseStore(None)
        store.init_db()
        store.reset_db()

    def tearDown(self):
        os.environ.pop("CRM_DB_PATH", None)
        os.environ.pop("CRM_POSTGRES_DSN", None)

    def test_health_and_metrics_endpoints(self):
        app = create_app(db_path=self.db_path)
        client = TestClient(app)

        health = client.get("/healthz")
        self.assertEqual(200, health.status_code)
        self.assertEqual("ok", health.json()["status"])

        metrics = client.get("/metrics")
        self.assertEqual(200, metrics.status_code)
        self.assertIn("crm_crawl_jobs_total", metrics.text)

    def test_crawl_job_submission_endpoint(self):
        app = create_app(db_path=self.db_path)
        client = TestClient(app)

        response = client.post(
            "/api/crawl",
            json={"urls": ["https://example.com"], "engine": "standard"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("queued", response.json()["status"])


if __name__ == "__main__":
    unittest.main()
