import hashlib
import re
import sqlite3
import sys
import urllib.request
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

sys.dont_write_bytecode = True


class DatabaseStore:
    def __init__(self, db_path="data.db"):
        self.db_path = db_path

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                company TEXT,
                source TEXT,
                status TEXT,
                interest TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                channel TEXT,
                budget REAL DEFAULT 0,
                target TEXT,
                status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS marketing_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                content TEXT NOT NULL,
                recipient_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'queued',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                status TEXT DEFAULT 'completed',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS company_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                company_name TEXT,
                contact_name TEXT,
                phone TEXT,
                email TEXT,
                address TEXT,
                industry TEXT,
                region TEXT,
                raw_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()
        self._ensure_default_admin_user()

    def _ensure_default_admin_user(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        row = cur.execute("SELECT 1 FROM users WHERE username = ?", ("admin",)).fetchone()
        if row is None:
            password_hash = hashlib.sha256(b"admin123").hexdigest()
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", password_hash, "admin"),
            )
            cur.execute(
                "INSERT INTO activity_log (action, details) VALUES (?, ?)",
                ("default_admin_created", "Created default admin account"),
            )
        conn.commit()
        conn.close()

    def add_lead(self, name, email, phone, company, source, status, interest, notes):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO leads (name, email, phone, company, source, status, interest, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, phone, company, source, status, interest, notes),
        )
        lead_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.log_activity("lead_created", f"Created lead {name}")
        return lead_id

    def add_campaign(self, name, channel, budget, target, status):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO campaigns (name, channel, budget, target, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, channel, budget, target, status),
        )
        conn.commit()
        conn.close()
        self.log_activity("campaign_created", f"Created campaign {name}")
        return True

    def add_marketing_message(self, channel, content, recipient_count, status="queued"):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO marketing_messages (channel, content, recipient_count, status)
            VALUES (?, ?, ?, ?)
            """,
            (channel, content, recipient_count, status),
        )
        conn.commit()
        conn.close()
        self.log_activity("message_created", f"Created {channel} marketing message")
        return True

    def create_user(self, username, password, role):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        conn.commit()
        conn.close()
        self.log_activity("user_created", f"Created user {username}")
        return True

    def authenticate_user(self, username, password):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if row["password_hash"] != password_hash:
            return None
        return dict(row)

    def add_crawl_job(self, url, title, summary, status="completed"):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO crawl_jobs (url, title, summary, status) VALUES (?, ?, ?, ?)",
            (url, title, summary, status),
        )
        job_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.log_activity("crawl_job_created", f"Captured crawl job {url}")
        return job_id

    def add_company_profile(self, url, profile_data):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO company_profiles (
                url, company_name, contact_name, phone, email, address, industry, region, raw_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                profile_data.get("company_name"),
                profile_data.get("contact_name"),
                profile_data.get("phone"),
                profile_data.get("email"),
                profile_data.get("address"),
                profile_data.get("industry"),
                profile_data.get("region"),
                profile_data.get("raw_text"),
            ),
        )
        profile_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.log_activity("company_profile_created", f"Captured company profile for {url}")
        return profile_id

    def list_company_profiles(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM company_profiles ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_company_profile(self, profile_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM company_profiles WHERE id = ?", (profile_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_company_profile(self, profile_id, profile_data):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE company_profiles
            SET company_name = ?, contact_name = ?, phone = ?, email = ?, address = ?, industry = ?, region = ?, url = ?
            WHERE id = ?
            """,
            (
                profile_data.get("company_name"),
                profile_data.get("contact_name"),
                profile_data.get("phone"),
                profile_data.get("email"),
                profile_data.get("address"),
                profile_data.get("industry"),
                profile_data.get("region"),
                profile_data.get("url"),
                profile_id,
            ),
        )
        conn.commit()
        conn.close()
        self.log_activity("company_profile_updated", f"Updated company profile {profile_id}")
        return True

    def log_activity(self, action, details):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO activity_log (action, details) VALUES (?, ?)",
            (action, details),
        )
        conn.commit()
        conn.close()

    def list_leads(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_campaigns(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_marketing_messages(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM marketing_messages ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_crawl_jobs(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM crawl_jobs ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_users(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_activity_log(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 50").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_dashboard_summary(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lead_count = cur.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"]
        campaign_count = cur.execute("SELECT COUNT(*) AS count FROM campaigns").fetchone()["count"]
        total_budget = cur.execute("SELECT COALESCE(SUM(budget), 0) AS total FROM campaigns").fetchone()["total"]
        recent_activity = cur.execute("SELECT COUNT(*) AS count FROM activity_log").fetchone()["count"]
        message_count = cur.execute("SELECT COUNT(*) AS count FROM marketing_messages").fetchone()["count"]
        user_count = cur.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        crawl_count = cur.execute("SELECT COUNT(*) AS count FROM crawl_jobs").fetchone()["count"]
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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lead_status_rows = cur.execute(
            "SELECT status, COUNT(*) AS count FROM leads GROUP BY status"
        ).fetchall()
        campaign_channel_rows = cur.execute(
            "SELECT channel, COUNT(*) AS count FROM campaigns GROUP BY channel"
        ).fetchall()
        message_status_rows = cur.execute(
            "SELECT status, COUNT(*) AS count FROM marketing_messages GROUP BY status"
        ).fetchall()
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
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8", errors="ignore")


def _extract_company_profile(text, title, base_url):
    cleaned = re.sub(r"\s+", " ", text).strip()
    company_name = None
    contact_name = None
    phone = None
    email = None
    address = None
    industry = None
    region = "北京"

    if title:
        company_name = title.strip()
    for pattern in [
        r"公司名称[:：]\s*(.*?)(?=(?:联系人|负责人|电话|手机|邮箱|办公地址|地址|行业|公司名称|企业名称|名称|$))",
        r"企业名称[:：]\s*(.*?)(?=(?:联系人|负责人|电话|手机|邮箱|办公地址|地址|行业|公司名称|企业名称|名称|$))",
        r"名称[:：]\s*(.*?)(?=(?:联系人|负责人|电话|手机|邮箱|办公地址|地址|行业|公司名称|企业名称|名称|$))",
    ]:
        m = re.search(pattern, cleaned)
        if m:
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            if candidate:
                company_name = candidate
                break
    for pattern in [
        r"联系人[:：]\s*(.*?)(?=(?:电话|手机|邮箱|办公地址|地址|行业|公司名称|企业名称|名称|\s*\S+[:：]))",
        r"负责人[:：]\s*(.*?)(?=(?:电话|手机|邮箱|办公地址|地址|行业|公司名称|企业名称|名称|\s*\S+[:：]))",
    ]:
        m = re.search(pattern, cleaned)
        if m:
            contact_name = re.sub(r"\s+", " ", m.group(1)).strip()
            break
    phone_match = re.search(r"(?:电话|手机)[:：]?\s*(1[3-9]\d{9}|\d{3,4}-\d{7,8})", cleaned)
    if phone_match:
        phone = phone_match.group(1).strip()
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned)
    if email_match:
        email = email_match.group(0)
    address_match = re.search(r"办公地址[:：]\s*(.*?)(?=(?:电话|手机|邮箱|行业|公司名称|企业名称|名称|\s*\S+[:：]|$))", cleaned)
    if address_match:
        address = re.sub(r"\s+", " ", address_match.group(1)).strip()
    industry_match = re.search(r"行业[:：]\s*(.*?)(?=(?:电话|手机|邮箱|办公地址|地址|公司名称|企业名称|名称|\s*\S+[:：]|$))", cleaned)
    if industry_match:
        industry = re.sub(r"\s+", " ", industry_match.group(1)).strip()

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
    profile = _extract_company_profile(text, title, base_url)
    result = {"title": title, "summary": unescape(summary), "links": links}
    result.update(profile)
    return result


def run_crawl_pipeline(url):
    try:
        import scrapy  # type: ignore

        _ = scrapy
        result = parse_html_content(fetch_url_content(url), url)
        result["engine"] = "scrapy"
        return result
    except Exception:
        result = parse_html_content(fetch_url_content(url), url)
        result["engine"] = "standard-library"
        return result


def main():
    store = DatabaseStore("data.db")
    store.init_db()
    print("CRM starter initialized")


if __name__ == "__main__":
    main()
