import os
import tempfile
import time
import unittest
import app as app_module

from app import (
    DEFAULT_BEIJING_TARGET_CANDIDATES,
    DatabaseStore,
    crawl_urls_once,
    dedupe_urls,
    discover_viable_targets,
    is_profile_in_region,
    normalize_urls,
    parse_html_content,
    record_crawl_cycle_summary,
    run_crawl_pipeline,
    should_pause_target,
)
from api import _ensure_background_crawler_running
import server


class AppLogicTests(unittest.TestCase):
    def setUp(self):
        os.environ["CRM_POSTGRES_DSN"] = "postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local"
        self.store = DatabaseStore(None)
        self.store.init_db()
        self.store.reset_db()

    def tearDown(self):
        os.environ.pop("CRM_POSTGRES_DSN", None)

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

    def test_company_profile_storage_only_keeps_relevant_fields(self):
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
            <p>备注：这段额外说明不应该被保存</p>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://example.com")
        profile_id = self.store.add_company_profile("https://example.com", result)
        profiles = self.store.list_company_profiles()
        self.assertEqual(1, len(profiles))
        self.assertEqual("北京XX科技有限公司", profiles[0]["company_name"])
        self.assertIsNone(profiles[0]["raw_text"])

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

    def test_company_profile_parsing_with_common_labels(self):
        html = """
        <html>
          <body>
            <h1>北京XX科技有限公司</h1>
            <p>公司名称：北京XX科技有限公司</p>
            <p>联系人：张先生</p>
            <p>联系电话：13800000000</p>
            <p>电子邮箱：zhang@example.com</p>
            <p>公司地址：北京市朝阳区望京SOHO</p>
            <p>主营业务：软件研发</p>
            <p>所在地区：北京</p>
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

    def test_company_profile_parsing_with_phone_label_variants(self):
        html = """
        <html>
          <body>
            <h1>北京XX科技有限公司</h1>
            <p>公司名称：北京XX科技有限公司</p>
            <p>联系人：张先生</p>
            <p>手机号：13800000000</p>
            <p>联系邮箱：zhang@example.com</p>
            <p>公司地址：北京市朝阳区望京SOHO</p>
            <p>主营业务：软件研发</p>
            <p>所在地区：北京</p>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://example.com")
        self.assertEqual("13800000000", result["phone"])
        self.assertEqual("zhang@example.com", result["email"])

    def test_region_is_not_forced_to_beijing_when_missing(self):
        html = """
        <html>
          <head><title>某科技公司</title></head>
          <body>
            <h1>某科技公司</h1>
            <p>联系人：王先生</p>
            <p>联系电话：13800000000</p>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://example.com")
        self.assertIsNone(result["region"])

    def test_is_profile_in_region_matches_beijing_districts(self):
        profile = {
            "company_name": "某某科技",
            "address": "海淀区中关村软件园",
            "region": None,
            "raw_text": "",
        }
        self.assertTrue(is_profile_in_region(profile, required_region="北京"))

    def test_crawl_urls_once_strict_region_filters_non_beijing(self):
        original_runner = app_module.run_crawl_pipeline

        def fake_runner(url, preferred_engine="auto"):
            return {
                "title": "测试企业",
                "summary": "测试摘要",
                "links": [],
                "company_name": "上海测试企业",
                "contact_name": "张三",
                "phone": "13800000000",
                "email": "z@example.com",
                "address": "上海市浦东新区",
                "industry": "软件",
                "region": "上海",
                "raw_text": "上海市浦东新区",
                "engine": "test",
            }

        try:
            app_module.run_crawl_pipeline = fake_runner
            summary = crawl_urls_once(
                self.store,
                ["https://example.com"],
                preferred_engine="standard",
                required_region="北京",
                strict_region=True,
            )
        finally:
            app_module.run_crawl_pipeline = original_runner

        self.assertEqual(0, summary["processed"])
        self.assertEqual(1, summary["filtered"])
        self.assertEqual(0, len(self.store.list_company_profiles()))

    def test_company_profile_parsing_from_jsonld_and_meta_tags(self):
        html = """
        <html>
          <head>
            <title>关于我们 | 智链科技</title>
            <meta property="og:site_name" content="智链科技" />
            <meta name="description" content="专注智能制造解决方案" />
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
            <p>我们提供智能制造解决方案</p>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://example.com")
        self.assertEqual("智链科技", result["company_name"])
        self.assertEqual("13800000000", result["phone"])
        self.assertEqual("contact@zhilian.com", result["email"])
        self.assertEqual("北京市朝阳区望京SOHO", result["address"])
        self.assertEqual("人工智能", result["industry"])
        self.assertEqual("北京", result["region"])

    def test_normalize_urls_supports_multiple_inputs(self):
        urls = normalize_urls("https://example.com\nhttps://baidu.com, https://bing.com")
        self.assertEqual(["https://example.com", "https://baidu.com", "https://bing.com"], urls)

    def test_dedupe_urls_removes_case_and_trailing_slash_duplicates(self):
        urls = dedupe_urls(["https://example.com", "https://example.com/", "HTTPS://EXAMPLE.COM"])
        self.assertEqual(["https://example.com"], urls)

    def test_append_crawl_targets_merges_without_overwriting_existing(self):
        self.store.save_crawl_targets(["https://example.com"])
        merged = self.store.append_crawl_targets(["https://example.com/", "https://baidu.com"])
        self.assertEqual(["https://example.com", "https://baidu.com"], merged)

    def test_discover_viable_targets_filters_by_score_and_region(self):
        original_fetch = app_module.fetch_url_content

        def fake_fetch(url):
            if "good" in url:
                return """
                <html><head><title>北京优质企业</title></head><body>
                <p>公司名称：北京优质企业有限公司</p>
                <p>联系电话：13800000000</p>
                <p>邮箱：hello@good.com</p>
                <p>地址：北京市海淀区中关村</p>
                <p>行业：软件服务</p>
                </body></html>
                """
            return """
            <html><head><title>外地企业</title></head><body>
            <p>公司名称：上海企业有限公司</p>
            <p>地址：上海市浦东新区</p>
            </body></html>
            """

        try:
            app_module.fetch_url_content = fake_fetch
            result = discover_viable_targets(
                ["https://good.example.com", "https://other.example.com"],
                required_region="北京",
                min_score=4,
                strict_region=True,
            )
        finally:
            app_module.fetch_url_content = original_fetch

        self.assertEqual(2, result["total"])
        self.assertEqual(1, len(result["viable"]))
        self.assertIn("good.example.com", result["viable"][0]["url"])
        self.assertEqual(1, len(result["rejected"]))

    def test_default_candidate_pool_is_not_empty(self):
        self.assertGreaterEqual(len(DEFAULT_BEIJING_TARGET_CANDIDATES), 5)

    def test_should_pause_target_on_failure_streak(self):
        paused = should_pause_target(success_count=1, failed_count=3, consecutive_failures=3, min_samples=5, failure_streak_threshold=3, min_success_rate=0.2)
        self.assertTrue(paused)

    def test_should_not_pause_with_good_success_rate(self):
        paused = should_pause_target(success_count=8, failed_count=1, consecutive_failures=0, min_samples=5, failure_streak_threshold=3, min_success_rate=0.2)
        self.assertFalse(paused)

    def test_revive_paused_targets_restores_viable_urls(self):
        original_discover = app_module.discover_viable_targets

        def fake_discover(urls, required_region="北京", min_score=4, strict_region=True):
            return {
                "total": len(urls),
                "viable": [{"url": urls[0], "score": 6}] if urls else [],
                "rejected": [{"url": urls[1], "score": 1, "reason": "low score"}] if len(urls) > 1 else [],
            }

        self.store.update_target_health("https://paused1.example.com", "failed", score=0, error="x")
        self.store.update_target_health("https://paused1.example.com", "failed", score=0, error="x")
        self.store.update_target_health("https://paused1.example.com", "failed", score=0, error="x")
        self.store.update_target_health("https://paused2.example.com", "failed", score=0, error="x")
        self.store.update_target_health("https://paused2.example.com", "failed", score=0, error="x")
        self.store.update_target_health("https://paused2.example.com", "failed", score=0, error="x")

        try:
            app_module.discover_viable_targets = fake_discover
            result = self.store.revive_paused_targets(required_region="北京", min_score=4, strict_region=True, limit=10)
        finally:
            app_module.discover_viable_targets = original_discover

        self.assertGreaterEqual(result["total"], 1)
        self.assertEqual(1, result["revived"])
        targets = self.store.get_crawl_target_urls()
        self.assertIn("https://paused1.example.com", targets)

    def test_run_crawl_pipeline_uses_standard_library_fallback(self):
        result = run_crawl_pipeline("https://example.com", preferred_engine="standard")
        self.assertIn("engine", result)
        self.assertTrue(result.get("title") or result.get("summary") or result.get("raw_text"))

    def test_crawl_urls_once_persists_results(self):
        summary = crawl_urls_once(self.store, ["https://example.com"], preferred_engine="standard")
        self.assertEqual(1, summary["processed"])
        jobs = self.store.list_crawl_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual("https://example.com", jobs[0]["url"])

    def test_crawl_targets_can_be_saved_and_loaded(self):
        self.store.save_crawl_targets(["https://example.com", "https://baidu.com"])
        self.assertEqual(["https://example.com", "https://baidu.com"], self.store.get_crawl_target_urls())

    def test_database_store_uses_postgres_when_dsn_is_configured(self):
        os.environ["CRM_POSTGRES_DSN"] = "postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local"
        try:
            store = DatabaseStore("ignored.db")
            store.init_db()
            job_id = store.add_crawl_job("https://example.com", "Example", "ok")
            jobs = store.list_crawl_jobs()
            self.assertIsNotNone(job_id)
            self.assertGreaterEqual(len(jobs), 1)
            if jobs:
                self.assertEqual("https://example.com", jobs[0]["url"])
        finally:
            os.environ.pop("CRM_POSTGRES_DSN", None)

    def test_background_crawler_loop_records_activity(self):
        self.store.save_crawl_targets(["https://example.com"])
        thread, stop_event = _ensure_background_crawler_running(
            self.store,
            urls=["https://example.com"],
            interval_seconds=0.1,
            auto_start=True,
        )
        deadline = time.time() + 5
        activity = self.store.get_activity_log()
        while time.time() < deadline:
            activity = self.store.get_activity_log()
            if any(item["action"] == "crawl_loop_tick" for item in activity):
                break
            time.sleep(0.1)
        if thread is not None:
            self.assertTrue(thread.is_alive())
            stop_event.set()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_server_toggle_background_crawler_stops_and_starts_loop(self):
        server.stop_background_crawler()
        server._ensure_background_crawler_running()
        self.assertIsNotNone(server.BACKGROUND_CRAWLER_THREAD)
        self.assertTrue(server.BACKGROUND_CRAWLER_THREAD.is_alive())
        server.stop_background_crawler()
        self.assertIsNone(server.BACKGROUND_CRAWLER_THREAD)
        self.assertIsNone(server.BACKGROUND_CRAWLER_STOP)
        server._ensure_background_crawler_running()
        self.assertTrue(server.is_background_crawler_running())

    def test_record_crawl_cycle_summary_writes_visible_stats(self):
        record_crawl_cycle_summary(self.store, 3, 1)
        latest = self.store.get_latest_crawl_cycle_summary()
        self.assertEqual(3, latest["processed"])
        self.assertEqual(1, latest["failed"])

    def test_company_profile_deduplicates_and_adds_status(self):
        first_id = self.store.add_company_profile(
            "https://example.com",
            {"company_name": "Acme", "phone": "13800000000", "email": "a@example.com", "industry": "AI", "region": "北京"},
        )
        second_id = self.store.add_company_profile(
            "https://example.com",
            {"company_name": "Acme", "phone": "13900000000", "email": "b@example.com", "industry": "人工智能", "region": "上海"},
        )
        self.assertEqual(first_id, second_id)
        profiles = self.store.list_company_profiles()
        self.assertEqual(1, len(profiles))
        self.assertEqual("updated", profiles[0]["status"])
        self.assertEqual("13900000000", profiles[0]["phone"])
        self.assertEqual("上海", profiles[0]["region"])

    def test_company_profile_filters(self):
        self.store.add_company_profile("https://a.com", {"company_name": "Alpha", "industry": "AI", "region": "北京"})
        self.store.add_company_profile("https://b.com", {"company_name": "Beta", "industry": "金融", "region": "深圳"})
        filtered = self.store.list_company_profiles(company_name="Alpha")
        self.assertEqual(1, len(filtered))
        self.assertEqual("Alpha", filtered[0]["company_name"])
        filtered_by_industry = self.store.list_company_profiles(industry="金融")
        self.assertEqual(1, len(filtered_by_industry))
        self.assertEqual("深圳", filtered_by_industry[0]["region"])

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
