import os
import sqlite3
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor


class PostgresStore:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("CRM_POSTGRES_DSN")
        self._conn = None

    def _connect(self):
        if self._conn is None:
            if not self.dsn:
                raise RuntimeError("CRM_POSTGRES_DSN is not configured")
            self._conn = psycopg2.connect(self.dsn)
        return self._conn

    def init_db(self):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    company TEXT,
                    source TEXT,
                    status TEXT,
                    interest TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_jobs (
                    id SERIAL PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    summary TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()
        return True

    def add_crawl_job(self, url, title, summary, status="completed"):
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO crawl_jobs (url, title, summary, status) VALUES (%s, %s, %s, %s) RETURNING id",
                (url, title, summary, status),
            )
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None

    def list_crawl_jobs(self):
        conn = self._connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM crawl_jobs ORDER BY created_at DESC")
            return [dict(row) for row in cur.fetchall()]
