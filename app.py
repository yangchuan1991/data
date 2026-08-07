import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:  # pragma: no cover
    sync_playwright = None

sys.dont_write_bytecode = True


class DatabaseStore:
    def __init__(self, db_path=None):
        self.db_path = db_path
        self.use_postgres = True

    def _connect(self):
        dsn = os.environ.get("CRM_POSTGRES_DSN")
        if not dsn:
            raise RuntimeError("CRM_POSTGRES_DSN must be set to a PostgreSQL connection string")

        import psycopg2

        conn = psycopg2.connect(dsn)
        self.use_postgres = True
        return conn

    def _cursor(self, conn):
        from psycopg2.extras import RealDictCursor

        return conn.cursor(cursor_factory=RealDictCursor)

    def _sql(self, sql):
        return sql.replace("?", "%s")

    def _normalize_row(self, row):
        if row is None:
            return None
        if hasattr(row, "keys"):
            return dict(row)
        if isinstance(row, (tuple, list)):
            return row
        return row

    def init_db(self):
        conn = self._connect()
        cur = self._cursor(conn)
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
            CREATE TABLE IF NOT EXISTS campaigns (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                channel TEXT,
                budget REAL DEFAULT 0,
                target TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS marketing_messages (
                id SERIAL PRIMARY KEY,
                channel TEXT NOT NULL,
                content TEXT NOT NULL,
                recipient_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'queued',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_target_urls (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_cycle_stats (
                id SERIAL PRIMARY KEY,
                processed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS company_profiles (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL,
                company_name TEXT,
                contact_name TEXT,
                phone TEXT,
                email TEXT,
                address TEXT,
                industry TEXT,
                region TEXT,
                raw_text TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'new'")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()
        self._ensure_default_admin_user()

    def reset_db(self):
        conn = self._connect()
        cur = self._cursor(conn)
        for table_name in [
            "activity_log",
            "company_profiles",
            "crawl_cycle_stats",
            "crawl_target_urls",
            "crawl_jobs",
            "marketing_messages",
            "campaigns",
            "leads",
            "users",
        ]:
            cur.execute(f"DELETE FROM {table_name}")
        conn.commit()
        conn.close()
        self._ensure_default_admin_user()

    def _ensure_default_admin_user(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT 1 FROM users WHERE username = ?"), ("admin",))
        row = cur.fetchone()
        if row is None:
            password_hash = hashlib.sha256(b"admin123").hexdigest()
            cur.execute(self._sql("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)"), ("admin", password_hash, "admin"))
            cur.execute(self._sql("INSERT INTO activity_log (action, details) VALUES (?, ?)"), ("default_admin_created", "Created default admin account"))
        conn.commit()
        conn.close()

    def add_lead(self, name, email, phone, company, source, status, interest, notes):
        conn = self._connect()
        cur = self._cursor(conn)
        if self.use_postgres:
            cur.execute(
                self._sql("""
                INSERT INTO leads (name, email, phone, company, source, status, interest, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """),
                (name, email, phone, company, source, status, interest, notes),
            )
            row = cur.fetchone()
            lead_id = row["id"] if row else None
        else:
            cur.execute(
                self._sql("""
                INSERT INTO leads (name, email, phone, company, source, status, interest, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """),
                (name, email, phone, company, source, status, interest, notes),
            )
            lead_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.log_activity("lead_created", f"Created lead {name}")
        return lead_id

    def add_campaign(self, name, channel, budget, target, status):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(
            self._sql("""
            INSERT INTO campaigns (name, channel, budget, target, status)
            VALUES (?, ?, ?, ?, ?)
            """),
            (name, channel, budget, target, status),
        )
        conn.commit()
        conn.close()
        self.log_activity("campaign_created", f"Created campaign {name}")
        return True

    def add_marketing_message(self, channel, content, recipient_count, status="queued"):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(
            self._sql("""
            INSERT INTO marketing_messages (channel, content, recipient_count, status)
            VALUES (?, ?, ?, ?)
            """),
            (channel, content, recipient_count, status),
        )
        conn.commit()
        conn.close()
        self.log_activity("message_created", f"Created {channel} marketing message")
        return True

    def create_user(self, username, password, role):
        conn = self._connect()
        cur = self._cursor(conn)
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        cur.execute(
            self._sql("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)") ,
            (username, password_hash, role),
        )
        conn.commit()
        conn.close()
        self.log_activity("user_created", f"Created user {username}")
        return True

    def authenticate_user(self, username, password):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(
            self._sql("SELECT * FROM users WHERE username = ?"),
            (username,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if row["password_hash"] != password_hash:
            return None
        return dict(row)

    def add_crawl_job(self, url, title, summary, status="completed"):
        conn = self._connect()
        cur = self._cursor(conn)
        if self.use_postgres:
            cur.execute(
                self._sql("INSERT INTO crawl_jobs (url, title, summary, status) VALUES (?, ?, ?, ?) RETURNING id"),
                (url, title, summary, status),
            )
            row = cur.fetchone()
            job_id = row["id"] if row else None
        else:
            cur.execute(
                self._sql("INSERT INTO crawl_jobs (url, title, summary, status) VALUES (?, ?, ?, ?)"),
                (url, title, summary, status),
            )
            job_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.log_activity("crawl_job_created", f"Captured crawl job {url}")
        return job_id

    def save_crawl_targets(self, urls):
        normalized_urls = []
        if isinstance(urls, str):
            candidate_urls = normalize_urls(urls)
        else:
            candidate_urls = normalize_urls("\n".join([str(item) for item in (urls or [])]))
        for item in candidate_urls:
            if item and item.strip():
                normalized_urls.append(item.strip())
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("DELETE FROM crawl_target_urls"))
        for item in normalized_urls:
            cur.execute(self._sql("INSERT INTO crawl_target_urls (url) VALUES (?)"), (item,))
        conn.commit()
        conn.close()
        self.log_activity("crawl_targets_updated", f"Configured {len(normalized_urls)} crawl targets")
        return normalized_urls

    def get_crawl_target_urls(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT url FROM crawl_target_urls ORDER BY id ASC"))
        rows = cur.fetchall()
        conn.close()
        return [row["url"] for row in rows]

    def get_latest_crawl_cycle_summary(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT processed, failed, created_at FROM crawl_cycle_stats ORDER BY id DESC LIMIT 1"))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"processed": 0, "failed": 0, "total": 0, "created_at": None}
        return {
            "processed": row["processed"],
            "failed": row["failed"],
            "total": row["processed"] + row["failed"],
            "created_at": row["created_at"],
        }

    def _normalize_profile_url(self, url):
        if not url:
            return None
        value = str(url).strip()
        if not value:
            return None
        parsed = urlparse(value)
        if not parsed.scheme:
            value = f"https://{value}"
            parsed = urlparse(value)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        return f"{scheme}://{netloc}{path}"

    def add_company_profile(self, url, profile_data):
        conn = self._connect()
        cur = self._cursor(conn)
        normalized_url = self._normalize_profile_url(url) or self._normalize_profile_url(profile_data.get("url"))
        if normalized_url:
            cur.execute(
                self._sql("SELECT id FROM company_profiles WHERE lower(url) = lower(?)"),
                (normalized_url,),
            )
            existing_row = cur.fetchone()
            if existing_row:
                profile_id = existing_row["id"]
                cur.execute(
                    self._sql("""
                    UPDATE company_profiles
                    SET url = ?, company_name = ?, contact_name = ?, phone = ?, email = ?, address = ?, industry = ?, region = ?, raw_text = ?, status = ?
                    WHERE id = ?
                    """),
                    (
                        normalized_url,
                        profile_data.get("company_name"),
                        profile_data.get("contact_name"),
                        profile_data.get("phone"),
                        profile_data.get("email"),
                        profile_data.get("address"),
                        profile_data.get("industry"),
                        profile_data.get("region"),
                        profile_data.get("raw_text"),
                        "updated",
                        profile_id,
                    ),
                )
                conn.commit()
                conn.close()
                self.log_activity("company_profile_updated", f"Updated company profile for {normalized_url}")
                return profile_id

        if self.use_postgres:
            cur.execute(
                self._sql("""
                INSERT INTO company_profiles (
                    url, company_name, contact_name, phone, email, address, industry, region, raw_text, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """),
                (
                    normalized_url or url,
                    profile_data.get("company_name"),
                    profile_data.get("contact_name"),
                    profile_data.get("phone"),
                    profile_data.get("email"),
                    profile_data.get("address"),
                    profile_data.get("industry"),
                    profile_data.get("region"),
                    profile_data.get("raw_text"),
                    "new",
                ),
            )
            row = cur.fetchone()
            profile_id = row["id"] if row else None
        else:
            cur.execute(
                self._sql("""
                INSERT INTO company_profiles (
                    url, company_name, contact_name, phone, email, address, industry, region, raw_text, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """),
                (
                    normalized_url or url,
                    profile_data.get("company_name"),
                    profile_data.get("contact_name"),
                    profile_data.get("phone"),
                    profile_data.get("email"),
                    profile_data.get("address"),
                    profile_data.get("industry"),
                    profile_data.get("region"),
                    profile_data.get("raw_text"),
                    "new",
                ),
            )
            profile_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.log_activity("company_profile_created", f"Captured company profile for {normalized_url or url}")
        return profile_id

    def list_company_profiles(self, company_name=None, industry=None, region=None, status=None):
        conn = self._connect()
        cur = self._cursor(conn)
        query = "SELECT * FROM company_profiles WHERE 1=1"
        params = []
        if company_name:
            query += " AND company_name LIKE ?"
            params.append(f"%{company_name}%")
        if industry:
            query += " AND industry LIKE ?"
            params.append(f"%{industry}%")
        if region:
            query += " AND region LIKE ?"
            params.append(f"%{region}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        cur.execute(self._sql(query), params)
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_company_profile(self, profile_id):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM company_profiles WHERE id = ?"), (profile_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_company_profile(self, profile_id, profile_data):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(
            self._sql("""
            UPDATE company_profiles
            SET company_name = ?, contact_name = ?, phone = ?, email = ?, address = ?, industry = ?, region = ?, url = ?, status = ?
            WHERE id = ?
            """),
            (
                profile_data.get("company_name"),
                profile_data.get("contact_name"),
                profile_data.get("phone"),
                profile_data.get("email"),
                profile_data.get("address"),
                profile_data.get("industry"),
                profile_data.get("region"),
                profile_data.get("url"),
                profile_data.get("status") or "updated",
                profile_id,
            ),
        )
        conn.commit()
        conn.close()
        self.log_activity("company_profile_updated", f"Updated company profile {profile_id}")
        return True

    def log_activity(self, action, details):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(
            self._sql("INSERT INTO activity_log (action, details) VALUES (?, ?)"),
            (action, details),
        )
        conn.commit()
        conn.close()

    def list_leads(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM leads ORDER BY created_at DESC"))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_campaigns(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM campaigns ORDER BY created_at DESC"))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_marketing_messages(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM marketing_messages ORDER BY created_at DESC"))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_crawl_jobs(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM crawl_jobs ORDER BY created_at DESC"))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_users(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM users ORDER BY created_at DESC"))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_activity_log(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 50"))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_dashboard_summary(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(self._sql("SELECT COUNT(*) AS count FROM leads"))
        lead_count = cur.fetchone()["count"]
        cur.execute(self._sql("SELECT COUNT(*) AS count FROM campaigns"))
        campaign_count = cur.fetchone()["count"]
        cur.execute(self._sql("SELECT COALESCE(SUM(budget), 0) AS total FROM campaigns"))
        total_budget = cur.fetchone()["total"]
        cur.execute(self._sql("SELECT COUNT(*) AS count FROM activity_log"))
        recent_activity = cur.fetchone()["count"]
        cur.execute(self._sql("SELECT COUNT(*) AS count FROM marketing_messages"))
        message_count = cur.fetchone()["count"]
        cur.execute(self._sql("SELECT COUNT(*) AS count FROM users"))
        user_count = cur.fetchone()["count"]
        cur.execute(self._sql("SELECT COUNT(*) AS count FROM crawl_jobs"))
        crawl_count = cur.fetchone()["count"]
        conn.close()
        return {
            "lead_count": lead_count,
            "campaign_count": campaign_count,
            "total_budget": float(total_budget),
            "recent_activity": recent_activity,
            "message_count": message_count,
            "user_count": user_count,
            "crawl_count": crawl_count,
        }

    def get_dashboard_chart_data(self):
        conn = self._connect()
        cur = self._cursor(conn)
        cur.execute(
            self._sql("SELECT status, COUNT(*) AS count FROM leads GROUP BY status")
        )
        lead_status_rows = cur.fetchall()
        cur.execute(
            self._sql("SELECT channel, COUNT(*) AS count FROM campaigns GROUP BY channel")
        )
        campaign_channel_rows = cur.fetchall()
        cur.execute(
            self._sql("SELECT status, COUNT(*) AS count FROM marketing_messages GROUP BY status")
        )
        message_status_rows = cur.fetchall()
        conn.close()
        return {
            "lead_status_breakdown": {row["status"] or "unknown": row["count"] for row in lead_status_rows},
            "campaign_channel_breakdown": {row["channel"] or "unknown": row["count"] for row in campaign_channel_rows},
            "message_status_breakdown": {row["status"] or "unknown": row["count"] for row in message_status_rows},
        }

    def build_report_payload(self):
        return {
            "leads": self.list_leads(),
            "campaigns": self.list_campaigns(),
            "messages": self.list_marketing_messages(),
            "crawls": self.list_crawl_jobs(),
            "users": self.list_users(),
            "company_profiles": self.list_company_profiles(),
        }

    def send_message(self, channel, content, recipient_count, status="queued"):
        self.add_marketing_message(channel=channel, content=content, recipient_count=recipient_count, status=status)
        self.log_activity("message_sent", f"Dispatched {channel} message")
        return True


class ContentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.text_parts = []
        self.links = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.links.append(value)
                    break

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def fetch_url_content(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8", errors="ignore")
            if not body or not body.strip():
                raise ValueError("抓取到的页面内容为空")
            return body
    except urllib.error.HTTPError as exc:
        raise ValueError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"网络访问失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ValueError("请求超时，请重试") from exc
    except Exception as exc:
        raise ValueError(f"抓取失败: {exc}") from exc


def _extract_company_profile(text, title, base_url, html_text=""):
    cleaned = re.sub(r"\s+", " ", text).strip()
    source_html = html_text or text
    company_name = None
    contact_name = None
    phone = None
    email = None
    address = None
    industry = None
    region = None

    if title:
        title_text = title.strip()
        if "|" in title_text:
            title_text = title_text.split("|")[-1].strip()
        if "-" in title_text:
            title_text = title_text.split("-")[-1].strip()
        company_name = title_text or title.strip()

    def _first_match(patterns, source=cleaned):
        for pattern in patterns:
            match = re.search(pattern, source)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip() if match.lastindex else match.group(0)
                if value:
                    return value
        return None

    def _normalize_phone(value):
        if not value:
            return None
        text = str(value).strip()
        match = re.search(r"(1[3-9]\d{9}|\d{3,4}[-－]?\d{7,8})", text)
        if match:
            return match.group(1)
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 11:
            return digits[-11:]
        return text

    def _normalize_email(value):
        if not value:
            return None
        match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", value)
        return match.group(1) if match else value.strip()

    def _normalize_address(value):
        if not value:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        if text.endswith(("北京", "上海", "广州", "深圳", "天津", "重庆", "香港", "澳门")):
            text = text.rsplit(" ", 1)[0]
        return text

    def _normalize_region(value):
        if not value:
            return None
        match = re.search(r"(北京|上海|广州|深圳|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门)", value)
        return match.group(1) if match else None

    # Try common structured metadata first.
    meta_patterns = [
        ("company_name", [r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']+)[\"']", r"<meta[^>]+name=[\"']application-name[\"'][^>]+content=[\"']([^\"']+)[\"']"]),
        ("phone", [r"<meta[^>]+itemprop=[\"']telephone[\"'][^>]+content=[\"']([^\"']+)[\"']", r"<meta[^>]+name=[\"']tel[\"'][^>]+content=[\"']([^\"']+)[\"']"]),
        ("email", [r"<meta[^>]+itemprop=[\"']email[\"'][^>]+content=[\"']([^\"']+)[\"']", r"<meta[^>]+name=[\"']email[\"'][^>]+content=[\"']([^\"']+)[\"']"]),
        ("address", [r"<meta[^>]+itemprop=[\"']address[\"'][^>]+content=[\"']([^\"']+)[\"']"]),
    ]
    for field, patterns in meta_patterns:
        value = _first_match(patterns, source_html)
        if value:
            value = re.sub(r"<[^>]+>", " ", value)
            value = re.sub(r"\s+", " ", value).strip()
            if field == "company_name":
                company_name = value
            elif field == "phone":
                phone = _normalize_phone(value)
            elif field == "email":
                email = _normalize_email(value)
            elif field == "address":
                address = _normalize_address(value)

    # JSON-LD / schema.org structured data.
    for schema_match in re.finditer(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", source_html, re.I | re.S):
        payload = schema_match.group(1)
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if isinstance(data, dict):
            if not company_name and data.get("name"):
                company_name = str(data["name"]).strip()
            if not phone and data.get("telephone"):
                phone = _normalize_phone(str(data["telephone"]))
            if not email and data.get("email"):
                email = _normalize_email(str(data["email"]))
            if not address and data.get("address"):
                if isinstance(data["address"], dict):
                    parts = []
                    if data["address"].get("streetAddress"):
                        parts.append(str(data["address"].get("streetAddress")))
                    if data["address"].get("addressRegion"):
                        parts.append(str(data["address"].get("addressRegion")))
                    if parts:
                        address = _normalize_address(" ".join(parts))
                else:
                    address = _normalize_address(str(data["address"]))
            if not industry and data.get("industry"):
                industry = str(data["industry"]).strip()
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if not company_name and item.get("name"):
                        company_name = str(item["name"]).strip()
                    if not phone and item.get("telephone"):
                        phone = _normalize_phone(str(item["telephone"]))
                    if not email and item.get("email"):
                        email = _normalize_email(str(item["email"]))
                    if not address and item.get("address"):
                        if isinstance(item["address"], dict):
                            parts = []
                            if item["address"].get("streetAddress"):
                                parts.append(str(item["address"].get("streetAddress")))
                            if item["address"].get("addressRegion"):
                                parts.append(str(item["address"].get("addressRegion")))
                            if parts:
                                address = _normalize_address(" ".join(parts))
                        else:
                            address = _normalize_address(str(item["address"]))
                    if not industry and item.get("industry"):
                        industry = str(item["industry"]).strip()

    company_name = _first_match([
        r"(?:公司名称|企业名称|单位名称|机构名称|公司名|企业名)[:：]\s*(.*?)(?=(?:联系人|负责人|联系电话|联系手机|电话|手机|邮箱|电子邮箱|办公地址|公司地址|地址|行业|主营业务|主营|所在地区|区域|$))",
        r"(?:名称)[:：]\s*(.*?)(?=(?:联系人|负责人|联系电话|联系手机|电话|手机|邮箱|电子邮箱|办公地址|公司地址|地址|行业|主营业务|主营|所在地区|区域|$))",
    ]) or company_name

    contact_name = _first_match([
        r"(?:联系人|负责人|业务联系人|项目负责人)[:：]\s*(.*?)(?=(?:联系电话|联系手机|电话|手机|邮箱|电子邮箱|办公地址|公司地址|地址|行业|主营业务|主营|所在地区|区域|$))",
    ])

    if not phone:
        phone_match = re.search(r"(?:联系电话|联系手机|手机号|电话|手机)[:：]?\s*(1[3-9]\d{9}|\d{3,4}[-－]?\d{7,8})", cleaned)
        if phone_match:
            phone = _normalize_phone(phone_match.group(1).strip())

    if not email:
        email_match = re.search(r"(?:邮箱|电子邮箱|联系邮箱|email)[:：]?\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", cleaned)
        if email_match:
            email = _normalize_email(email_match.group(1))
        elif re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned):
            email = _normalize_email(re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned).group(0))

    if not address:
        address = _first_match([
            r"(?:办公地址|公司地址|联系地址|地址)[:：]\s*(.*?)(?=(?:联系人|负责人|联系电话|联系手机|手机号|电话|手机|邮箱|电子邮箱|联系邮箱|行业|主营业务|主营|所在地区|区域|$))",
        ])
        address = _normalize_address(address)

    if not industry:
        industry = _first_match([
            r"(?:行业|主营业务|业务范围|主营|业务类别)[:：]\s*(.*?)(?=(?:联系人|负责人|联系电话|联系手机|手机号|电话|手机|邮箱|电子邮箱|联系邮箱|办公地址|公司地址|地址|所在地区|区域|$))",
        ])

    if not region:
        region_match = re.search(r"(?:所在地区|地区|区域|城市)[:：]\s*(北京|上海|广州|深圳|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门)", cleaned)
        if region_match:
            region = region_match.group(1)
        elif address:
            region = _normalize_region(address)
    if region is None:
        region = "北京"

    return {
        "company_name": company_name,
        "contact_name": contact_name,
        "phone": phone,
        "email": email,
        "address": address,
        "industry": industry,
        "region": region,
        "raw_text": cleaned,
    }


def normalize_urls(raw_value):
    items = []
    for line in str(raw_value or "").replace("\r", "\n").splitlines():
        for chunk in line.split(","):
            candidate = chunk.strip()
            if not candidate:
                continue
            if not candidate.startswith(("http://", "https://")):
                candidate = f"https://{candidate}"
            items.append(candidate)
    return items


def parse_html_content(html_text, base_url):
    parser = ContentParser()
    parser.feed(html_text)
    parser.close()
    title = unescape("".join(parser.title_parts).strip())
    text = " ".join(part for part in parser.text_parts if part and part.strip())
    summary = re.sub(r"\s+", " ", text[:500]).strip()
    links = []
    for link in parser.links:
        if link.startswith("http"):
            links.append(link)
        else:
            links.append(urljoin(base_url, link))
    profile = _extract_company_profile(text, title, base_url, html_text)
    result = {"title": title, "summary": unescape(summary), "links": links}
    result.update(profile)
    return result


def _fetch_with_playwright(url):
    if sync_playwright is None:
        raise RuntimeError("playwright not available")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()
        return html


def run_crawl_pipeline(url, preferred_engine="auto"):
    if preferred_engine == "playwright":
        try:
            html = _fetch_with_playwright(url)
            result = parse_html_content(html, url)
            result["engine"] = "playwright"
            return result
        except Exception as exc:
            raise ValueError(f"浏览器渲染抓取失败: {exc}") from exc

    if preferred_engine in {"auto", "playwright"}:
        try:
            html = _fetch_with_playwright(url)
            result = parse_html_content(html, url)
            result["engine"] = "playwright"
            return result
        except Exception:
            pass

    try:
        import scrapy  # type: ignore

        _ = scrapy
        result = parse_html_content(fetch_url_content(url), url)
        result["engine"] = "scrapy"
        return result
    except Exception:
        try:
            result = parse_html_content(fetch_url_content(url), url)
            result["engine"] = "standard-library"
            return result
        except Exception as secondary_exc:
            return {
                "title": "",
                "summary": str(secondary_exc),
                "links": [],
                "company_name": None,
                "contact_name": None,
                "phone": None,
                "email": None,
                "address": None,
                "industry": None,
                "region": "北京",
                "raw_text": str(secondary_exc),
                "engine": "failed",
            }


def crawl_urls_once(store, urls, preferred_engine="auto"):
    store.init_db()
    processed = 0
    failed = 0
    for url in urls:
        try:
            result = run_crawl_pipeline(url, preferred_engine=preferred_engine)
            store.add_crawl_job(url, result.get("title", ""), result.get("summary", ""), "completed")
            store.add_company_profile(url, result)
            store.log_activity("crawl_completed", f"Crawled {url} via {result.get('engine', 'unknown')}")
            processed += 1
        except Exception as exc:
            reason = str(exc)
            store.add_crawl_job(url, "", reason, "failed")
            store.log_activity("crawl_failed", reason)
            failed += 1
    summary = {"processed": processed, "failed": failed, "total": processed + failed}
    record_crawl_cycle_summary(store, summary["processed"], summary["failed"])
    return summary


def record_crawl_cycle_summary(store, processed, failed):
    conn = store._connect()
    cur = store._cursor(conn)
    cur.execute(
        store._sql("INSERT INTO crawl_cycle_stats (processed, failed) VALUES (?, ?)"),
        (processed, failed),
    )
    conn.commit()
    conn.close()
    return {"processed": processed, "failed": failed, "total": processed + failed}


def start_background_crawler(store, urls=None, interval_seconds=30, stop_event=None):
    if stop_event is None:
        stop_event = threading.Event()

    def _runner():
        while not stop_event.is_set():
            try:
                target_urls = store.get_crawl_target_urls()
                if not target_urls:
                    fallback_urls = [item.strip() for item in (urls or []) if item and item.strip()]
                    if not fallback_urls:
                        fallback_urls = ["https://example.com"]
                    target_urls = fallback_urls
                summary = crawl_urls_once(store, target_urls, preferred_engine="standard")
                store.log_activity(
                    "crawl_loop_tick",
                    f"Background crawl tick processed {summary['processed']} URLs, failed {summary['failed']}",
                )
            except Exception as exc:
                store.log_activity("crawl_loop_error", str(exc))
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=_runner, daemon=True, name="background-crawler")
    thread.start()
    return thread, stop_event


def main():
    if not os.environ.get("CRM_POSTGRES_DSN"):
        raise RuntimeError("CRM_POSTGRES_DSN must be set to a PostgreSQL connection string")
    store = DatabaseStore(None)
    store.init_db()
    print("CRM starter initialized")


if __name__ == "__main__":
    main()
