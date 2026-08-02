import os
import tempfile
import unittest

from app import DatabaseStore, parse_html_content


class AppLogicTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.store = DatabaseStore(self.db_path)
        self.store.init_db()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_init_db_and_create_lead(self):
        lead_id = self.store.add_lead(
            name="Alice",
            email="alice@example.com",
            phone="13800000000",
            company="Acme",
            source="website",
            status="new",
            interest="B2B",
            notes="Needs demo",
        )
        self.assertIsNotNone(lead_id)
        leads = self.store.list_leads()
        self.assertEqual(1, len(leads))
        self.assertEqual("Alice", leads[0]["name"])
        self.assertEqual("new", leads[0]["status"])

    def test_add_campaign_and_dashboard_summary(self):
        self.store.add_campaign(
            name="Q3 Launch",
            channel="email",
            budget=3000,
            target="SMB clients",
            status="running",
        )
        summary = self.store.get_dashboard_summary()
        self.assertEqual(1, summary["campaign_count"])
        self.assertGreaterEqual(summary["total_budget"], 3000)

    def test_parse_html_content_extracts_title_and_links(self):
        html = """
        <html>
          <head><title>Acme Growth</title></head>
          <body>
            <h1>Acme Growth</h1>
            <p>We help teams grow faster.</p>
            <a href="https://example.com/contact">Contact</a>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://example.com")
        self.assertEqual("Acme Growth", result["title"])
        self.assertIn("grow faster", result["summary"])
        self.assertEqual(["https://example.com/contact"], result["links"])

    def test_dashboard_chart_and_marketing_user_features(self):
        self.store.add_lead(name="Bob", email="bob@example.com", phone="", company="", source="web", status="new", interest="", notes="")
        self.store.add_lead(name="Carol", email="carol@example.com", phone="", company="", source="referral", status="contacted", interest="", notes="")
        self.store.add_campaign(name="Spring", channel="email", budget=1000, target="SMB", status="running")
        self.store.add_campaign(name="Summer", channel="sms", budget=500, target="Retail", status="paused")
        self.store.add_marketing_message(channel="email", content="Launch now", recipient_count=10, status="queued")
        self.store.create_user("manager", "p@ssw0rd", "manager")
        user = self.store.authenticate_user("manager", "p@ssw0rd")

        chart = self.store.get_dashboard_chart_data()
        self.assertEqual(1, chart["lead_status_breakdown"].get("new", 0))
        self.assertEqual(1, chart["lead_status_breakdown"].get("contacted", 0))
        self.assertEqual(1, chart["campaign_channel_breakdown"].get("email", 0))
        self.assertEqual(1, chart["campaign_channel_breakdown"].get("sms", 0))
        self.assertEqual("manager", user["role"])
        self.assertEqual(1, len(self.store.list_marketing_messages()))

    def test_crawl_job_storage(self):
        job_id = self.store.add_crawl_job(url="https://example.com", title="Example", summary="Example page")
        self.assertIsNotNone(job_id)
        jobs = self.store.list_crawl_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual("Example", jobs[0]["title"])

    def test_company_profile_parsing_and_storage(self):
        html = """
        <html>
          <head><title>北京XX科技有限公司</title></head>
          <body>
            <h1>北京XX科技有限公司</h1>
            <p>联系人：张先生</p>
            <p>电话：13800000000</p>
            <p>邮箱：zhang@example.com</p>
            <p>办公地址：北京市朝阳区望京SOHO</p>
            <p>行业：软件研发</p>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://example.com")
        self.assertEqual("北京XX科技有限公司", result["company_name"])
        self.assertEqual("张先生", result["contact_name"])
        self.assertEqual("13800000000", result["phone"])
        self.assertEqual("zhang@example.com", result["email"])
        self.assertEqual("北京市朝阳区望京SOHO", result["address"])
        self.assertEqual("软件研发", result["industry"])
        self.assertEqual("北京", result["region"])

        profile_id = self.store.add_company_profile("https://example.com", result)
        self.assertIsNotNone(profile_id)
        profiles = self.store.list_company_profiles()
        self.assertEqual(1, len(profiles))
        self.assertEqual("北京XX科技有限公司", profiles[0]["company_name"])

    def test_get_company_profile_by_id(self):
        result = parse_html_content(
            "<html><head><title>北京XX科技有限公司</title></head><body><p>公司名称：北京XX科技有限公司</p><p>联系人：张先生</p><p>电话：13800000000</p></body></html>",
            "https://example.com",
        )
        profile_id = self.store.add_company_profile("https://example.com", result)
        profile = self.store.get_company_profile(profile_id)
        self.assertEqual(profile_id, profile["id"])
        self.assertEqual("北京XX科技有限公司", profile["company_name"])

    def test_update_company_profile(self):
        result = parse_html_content(
            "<html><head><title>北京XX科技有限公司</title></head><body><p>公司名称：北京XX科技有限公司</p><p>联系人：张先生</p><p>电话：13800000000</p></body></html>",
            "https://example.com",
        )
        profile_id = self.store.add_company_profile("https://example.com", result)
        updated = {
            "company_name": "北京XX科技有限公司",
            "contact_name": "李小姐",
            "phone": "13900000000",
            "email": "li@example.com",
            "address": "北京市海淀区",
            "industry": "人工智能",
            "region": "北京",
            "url": "https://example.com/profile",
        }
        self.store.update_company_profile(profile_id, updated)
        profile = self.store.get_company_profile(profile_id)
        self.assertEqual("李小姐", profile["contact_name"])
        self.assertEqual("13900000000", profile["phone"])

    def test_auth_and_export_payload(self):
        self.store.create_user("analyst", "secret", "viewer")
        user = self.store.authenticate_user("analyst", "secret")
        self.assertEqual("viewer", user["role"])

        self.store.add_lead(name="Dana", email="dana@example.com", phone="", company="", source="", status="qualified", interest="", notes="")
        report = self.store.build_report_payload()
        self.assertIn("leads", report)
        self.assertEqual(1, len(report["leads"]))

    def test_default_admin_account_is_created(self):
        user = self.store.authenticate_user("admin", "admin123")
        self.assertIsNotNone(user)
        self.assertEqual("admin", user["role"])


if __name__ == "__main__":
    unittest.main()
