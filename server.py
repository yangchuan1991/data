import cgi
import csv
import html
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

sys.dont_write_bytecode = True

from app import (
    DEFAULT_BEIJING_TARGET_CANDIDATES,
    DatabaseStore,
    crawl_urls_once,
    discover_viable_targets,
    normalize_urls,
    start_background_crawler,
)

if not os.environ.get("CRM_POSTGRES_DSN"):
    raise RuntimeError("CRM_POSTGRES_DSN must be set to a PostgreSQL connection string")

store = DatabaseStore(None)
store.init_db()
BACKGROUND_CRAWLER_URLS = []
BACKGROUND_CRAWLER_STOP = None
BACKGROUND_CRAWLER_THREAD = None


def _ensure_background_crawler_running():
    global BACKGROUND_CRAWLER_STOP, BACKGROUND_CRAWLER_THREAD
    if BACKGROUND_CRAWLER_THREAD is not None and BACKGROUND_CRAWLER_THREAD.is_alive():
        return
    BACKGROUND_CRAWLER_THREAD, BACKGROUND_CRAWLER_STOP = start_background_crawler(
        store,
        urls=store.get_crawl_target_urls() or BACKGROUND_CRAWLER_URLS,
        interval_seconds=30,
        stop_event=None,
    )


def stop_background_crawler():
    global BACKGROUND_CRAWLER_STOP, BACKGROUND_CRAWLER_THREAD
    if BACKGROUND_CRAWLER_STOP is not None:
        BACKGROUND_CRAWLER_STOP.set()
    if BACKGROUND_CRAWLER_THREAD is not None:
        BACKGROUND_CRAWLER_THREAD.join(timeout=2)
    BACKGROUND_CRAWLER_STOP = None
    BACKGROUND_CRAWLER_THREAD = None


def is_background_crawler_running():
    return BACKGROUND_CRAWLER_THREAD is not None and BACKGROUND_CRAWLER_THREAD.is_alive()


_ensure_background_crawler_running()


class CRMHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._send_html(self._render_login())
            return
        if parsed.path == "/logout":
            self._clear_session()
            self._redirect("/login")
            return
        if parsed.path == "/export.csv":
            self._require_role(["admin", "manager"])
            self._send_csv(store.build_report_payload())
            return
        if parsed.path == "/export.json":
            self._require_role(["admin", "manager"])
            self._send_json(store.build_report_payload())
            return
        if parsed.path == "/export.company.csv":
            self._require_role(["admin", "manager"])
            self._send_company_csv(store.build_report_payload())
            return
        if parsed.path == "/":
            if not self._is_authenticated():
                self._redirect("/login")
                return
            self._send_html(self._render_dashboard())
            return
        if parsed.path.startswith("/company/"):
            if not self._is_authenticated():
                self._redirect("/login")
                return
            profile_id = parsed.path.split("/", 2)[-1]
            try:
                profile_id = int(profile_id)
            except ValueError:
                self._send_text(404, "Not found")
                return
            self._send_html(self._render_company_detail(profile_id))
            return
        self._send_text(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        params = self._parse_form_data()

        if parsed.path == "/login":
            username = self._get_first(params, "username", "")
            password = self._get_first(params, "password", "")
            user = store.authenticate_user(username, password)
            if user:
                session_id = str(uuid.uuid4())
                self._set_session(session_id, user)
                self.send_response(303)
                self.send_header("Set-Cookie", f"session_id={session_id}; Path=/")
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self._redirect("/login")
            return

        if not self._is_authenticated():
            self._redirect("/login")
            return

        if parsed.path == "/crawler/toggle":
            self._require_role(["admin", "manager"])
            if is_background_crawler_running():
                stop_background_crawler()
            else:
                _ensure_background_crawler_running()
            self._redirect("/")
            return

        if parsed.path.startswith("/company/") and parsed.path.endswith("/edit"):
            self._require_role(["admin", "manager"])
            profile_id = parsed.path.split("/", 2)[-2]
            try:
                profile_id = int(profile_id)
            except ValueError:
                self._send_text(404, "Not found")
                return
            store.update_company_profile(
                profile_id,
                {
                    "company_name": self._get_first(params, "company_name", ""),
                    "contact_name": self._get_first(params, "contact_name", ""),
                    "phone": self._get_first(params, "phone", ""),
                    "email": self._get_first(params, "email", ""),
                    "address": self._get_first(params, "address", ""),
                    "industry": self._get_first(params, "industry", ""),
                    "region": self._get_first(params, "region", ""),
                    "url": self._get_first(params, "url", ""),
                },
            )
            self._redirect(f"/company/{profile_id}")
            return

        if parsed.path == "/leads":
            self._require_role(["admin", "manager", "viewer"])
            store.add_lead(
                name=self._get_first(params, "name"),
                email=self._get_first(params, "email"),
                phone=self._get_first(params, "phone"),
                company=self._get_first(params, "company"),
                source=self._get_first(params, "source"),
                status=self._get_first(params, "status", "new"),
                interest=self._get_first(params, "interest"),
                notes=self._get_first(params, "notes"),
            )
        elif parsed.path == "/campaigns":
            self._require_role(["admin", "manager"])
            store.add_campaign(
                name=self._get_first(params, "name"),
                channel=self._get_first(params, "channel"),
                budget=float(self._get_first(params, "budget", "0") or 0),
                target=self._get_first(params, "target"),
                status=self._get_first(params, "status", "running"),
            )
        elif parsed.path == "/crawl":
            self._require_role(["admin", "manager"])
            raw_url = self._get_first(params, "targets", "").strip()
            preferred_engine = self._get_first(params, "engine", "auto")
            required_region = self._get_first(params, "required_region", "北京").strip() or "北京"
            strict_region = self._get_first(params, "strict_region", "on") in {"on", "1", "true", "yes"}
            if not raw_url:
                uploaded_value = self._get_first(params, "urls_file", "")
                if uploaded_value:
                    raw_url = uploaded_value
            urls = normalize_urls(raw_url)
            if urls:
                store.save_crawl_targets(urls)
                summary = crawl_urls_once(
                    store,
                    urls,
                    preferred_engine=preferred_engine,
                    required_region=required_region,
                    strict_region=strict_region,
                )
                store.log_activity(
                    "crawl_batch_completed",
                    f"Processed {summary['processed']} URLs, filtered {summary['filtered']}, failed {summary['failed']}",
                )
        elif parsed.path == "/crawl/discover":
            self._require_role(["admin", "manager"])
            raw_candidates = self._get_first(params, "candidate_targets", "").strip()
            required_region = self._get_first(params, "required_region", "北京").strip() or "北京"
            strict_region = self._get_first(params, "strict_region", "on") in {"on", "1", "true", "yes"}
            crawl_after_discovery = self._get_first(params, "crawl_after_discovery", "on") in {"on", "1", "true", "yes"}
            preferred_engine = self._get_first(params, "engine", "standard")
            try:
                min_score = int(self._get_first(params, "min_score", "4") or 4)
            except ValueError:
                min_score = 4
            candidate_urls = normalize_urls(raw_candidates) if raw_candidates else list(DEFAULT_BEIJING_TARGET_CANDIDATES)
            discovery = discover_viable_targets(
                candidate_urls,
                required_region=required_region,
                min_score=min_score,
                strict_region=strict_region,
            )
            for item in discovery.get("viable", []):
                store.update_target_health(item["url"], "completed", score=item.get("score", 0))
            for item in discovery.get("rejected", []):
                status = "filtered" if "not in" in str(item.get("reason", "")) else "failed"
                store.update_target_health(item["url"], status, score=item.get("score", 0), error=item.get("reason"))
            viable_urls = [item["url"] for item in discovery.get("viable", [])]
            if viable_urls:
                store.append_crawl_targets(viable_urls)
                if crawl_after_discovery:
                    summary = crawl_urls_once(
                        store,
                        viable_urls,
                        preferred_engine=preferred_engine,
                        required_region=required_region,
                        strict_region=strict_region,
                    )
                    store.log_activity(
                        "crawl_discovery_crawled",
                        f"Discovery crawl processed {summary['processed']}, filtered {summary['filtered']}, failed {summary['failed']}",
                    )
            store.log_activity(
                "crawl_discovery_completed",
                f"Discovery total {discovery['total']}, viable {len(viable_urls)}, rejected {len(discovery['rejected'])}",
            )
        elif parsed.path == "/crawl/prune-paused":
            self._require_role(["admin", "manager"])
            removed = store.prune_paused_targets()
            store.log_activity("crawl_prune_paused", f"Removed {len(removed)} paused targets from target pool")
        elif parsed.path == "/crawl/revive-paused":
            self._require_role(["admin", "manager"])
            required_region = self._get_first(params, "required_region", "北京").strip() or "北京"
            strict_region = self._get_first(params, "strict_region", "on") in {"on", "1", "true", "yes"}
            try:
                min_score = int(self._get_first(params, "min_score", "4") or 4)
            except ValueError:
                min_score = 4
            result = store.revive_paused_targets(required_region=required_region, min_score=min_score, strict_region=strict_region, limit=30)
            store.log_activity("crawl_revive_paused", f"Revived {result['revived']} targets, rejected {result['rejected']}")
        elif parsed.path == "/company-profiles/clear-history":
            self._require_role(["admin", "manager"])
            store.clear_company_profiles()
        elif parsed.path == "/messages":
            self._require_role(["admin", "manager"])
            store.add_marketing_message(
                channel=self._get_first(params, "channel", "email"),
                content=self._get_first(params, "content", ""),
                recipient_count=int(self._get_first(params, "recipient_count", "0") or 0),
                status=self._get_first(params, "status", "queued"),
            )
        elif parsed.path == "/users":
            self._require_role(["admin"])
            store.create_user(
                username=self._get_first(params, "username", ""),
                password=self._get_first(params, "password", ""),
                role=self._get_first(params, "role", "viewer"),
            )
        else:
            self._send_text(404, "Not found")
            return

        self._redirect("/")

    def _render_login(self):
        return """
        <!doctype html>
        <html lang=\"zh-CN\">
          <head><meta charset=\"utf-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /><title>登录</title>
          <style>body{font-family:Arial,sans-serif;background:#f5f7fb;display:flex;align-items:center;justify-content:center;height:100vh;} .card{background:#fff;padding:24px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.08);width:360px;} input,button{width:100%;padding:10px;border-radius:8px;border:1px solid #ddd;margin-top:10px;} button{background:#2563eb;color:#fff;cursor:pointer;}</style></head>
          <body><div class=\"card\"><h2>登录获客系统</h2><form method=\"post\" action=\"/login\"><input name=\"username\" placeholder=\"用户名\" required /><input name=\"password\" type=\"password\" placeholder=\"密码\" required /><button type=\"submit\">登录</button></form><p>默认可使用管理员账号：<strong>admin</strong> / <strong>admin123</strong></p></div></body></html>
        """

    def _render_dashboard(self):
                summary = store.get_dashboard_summary()
                latest_cycle = store.get_latest_crawl_cycle_summary()
                chart = store.get_dashboard_chart_data()
                activity = store.get_activity_log()
                users = store.list_users()
                target_health = store.list_target_health(limit=12)
                user = self._current_user()

                company_filters = {
                        "company_name": self._get_query_param("company_name"),
                        "industry": self._get_query_param("industry"),
                        "region": self._get_query_param("region") or "北京",
                        "status": self._get_query_param("status"),
                }
                company_profiles = store.list_company_profiles(**{k: v for k, v in company_filters.items() if v})
                configured_targets = "\n".join(store.get_crawl_target_urls())
                crawler_running = is_background_crawler_running()
                crawler_button_label = "启动后台抓取" if not crawler_running else "停止后台抓取"
                role_label = html.escape(str(user.get("role", "viewer"))) if user else "visitor"
                export_links = '<a href="/export.csv">导出总览 CSV</a> | <a href="/export.company.csv">导出企业 CSV</a> | <a href="/export.json">导出 JSON</a> | <a href="/logout">退出登录</a>'

                company_rows = "".join(
                        f"<tr><td><a href='/company/{item['id']}'>{html.escape(str(item['company_name'] or ''))}</a></td><td>{html.escape(str(item['contact_name'] or ''))}</td><td>{html.escape(str(item['phone'] or ''))}</td><td>{html.escape(str(item['email'] or ''))}</td><td>{html.escape(str(item['address'] or ''))}</td><td>{html.escape(str(item['industry'] or ''))}</td><td>{html.escape(str(item['region'] or ''))}</td><td>{html.escape(str(item['status'] or ''))}</td></tr>"
                        for item in company_profiles
                )
                activity_rows = "".join(
                        f"<tr><td>{html.escape(str(item['action']))}</td><td>{html.escape(str(item['details']))}</td><td>{html.escape(str(item['created_at']))}</td></tr>"
                        for item in activity
                )
                user_rows = "".join(
                        f"<tr><td>{html.escape(str(item['username']))}</td><td>{html.escape(str(item['role']))}</td><td>{html.escape(str(item['created_at']))}</td></tr>"
                        for item in users
                )
                target_rows = "".join(
                    f"<tr><td>{html.escape(str(item['url']))}</td><td>{item['success_count']}</td><td>{item['failed_count']}</td><td>{item['consecutive_failures']}</td><td>{item['filtered_count']}</td><td>{round(float(item['avg_score'] or 0), 2)}</td><td>{'yes' if item.get('is_paused') else 'no'}</td><td>{html.escape(str(item.get('pause_reason') or '-'))}</td><td>{html.escape(str(item['last_status'] or '-'))}</td></tr>"
                        for item in target_health
                )
                lead_bars = self._build_bar_chart(chart.get("lead_status_breakdown", {}), "线索状态")
                campaign_bars = self._build_bar_chart(chart.get("campaign_channel_breakdown", {}), "渠道分布")
                message_bars = self._build_bar_chart(chart.get("message_status_breakdown", {}), "营销消息状态")

                return f"""
                <!doctype html>
                <html lang=\"zh-CN\">
                    <head>
                        <meta charset=\"utf-8\" />
                        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
                        <title>获客系统控制台</title>
                        <script src=\"https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js\"></script>
                        <style>
                            body {{ font-family: Arial, sans-serif; margin: 0; background: #f5f7fb; color: #223; }}
                            .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
                            .card {{ background: #fff; padding: 18px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.06); margin-bottom: 16px; }}
                            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
                            .stat {{ background: linear-gradient(135deg, #4f46e5, #2563eb); color: white; padding: 16px; border-radius: 12px; }}
                            form {{ display: grid; gap: 10px; }}
                            input, select, textarea, button {{ padding: 10px; border-radius: 8px; border: 1px solid #ddd; font-size: 14px; }}
                            button {{ background: #2563eb; color: white; cursor: pointer; }}
                            table {{ width: 100%; border-collapse: collapse; }}
                            th, td {{ padding: 10px; border-bottom: 1px solid #eee; text-align: left; }}
                            .bar-chart {{ display: grid; gap: 8px; }}
                            .bar-row {{ display: flex; align-items: center; gap: 10px; }}
                            .bar {{ background: #e2e8f0; border-radius: 999px; height: 10px; flex: 1; overflow: hidden; }}
                            .bar > span {{ display: block; height: 100%; background: linear-gradient(90deg, #4f46e5, #38bdf8); }}
                            #chart {{ width: 100%; height: 320px; }}
                        </style>
                    </head>
                    <body>
                        <div class=\"container\">
                            <h1>获客系统控制台</h1>
                            <p>当前角色：{role_label}。{export_links}</p>
                            <div class=\"grid\">
                                <div class=\"stat\"><h3>线索总数</h3><div>{summary['lead_count']}</div></div>
                                <div class=\"stat\"><h3>营销活动</h3><div>{summary['campaign_count']}</div></div>
                                <div class=\"stat\"><h3>总预算</h3><div>{summary['total_budget']}</div></div>
                                <div class=\"stat\"><h3>消息数</h3><div>{summary['message_count']}</div></div>
                                <div class=\"stat\"><h3>用户数</h3><div>{summary['user_count']}</div></div>
                                   <div class="stat"><h3>企业资料</h3><div>{len(company_profiles)}</div></div>
                            </div>

                            <div class=\"card\">
                                <h2>图表分析（ECharts）</h2>
                                <div id=\"chart\"></div>
                                <script>
                                    const chart = echarts.init(document.getElementById('chart'));
                                    chart.setOption({{
                                        title:{{text:'线索与营销趋势'}},
                                        tooltip:{{trigger:'axis'}},
                                        legend:{{data:['线索','消息','活动']}},
                                        xAxis:{{type:'category', data:['线索','消息','活动']}},
                                        yAxis:{{type:'value'}},
                                        series:[{{name:'线索',type:'bar',data:[{summary['lead_count']}] }},{{name:'消息',type:'bar',data:[{summary['message_count']}] }},{{name:'活动',type:'bar',data:[{summary['campaign_count']}]}}]
                                    }});
                                </script>
                                <div class=\"grid\"><div>{lead_bars}</div><div>{campaign_bars}</div><div>{message_bars}</div></div>
                            </div>

                            <div class=\"card\">
                                <h2>抓取网址</h2>
                                <p>后台每 30 秒自动抓取目标并写入数据库。建议保持北京严格过滤开启。</p>
                                <form method=\"post\" action=\"/crawl\" enctype=\"multipart/form-data\">
                                    <textarea name=\"targets\" rows=\"4\" placeholder=\"换行或逗号分隔网址\">{html.escape(configured_targets)}</textarea>
                                    <input type=\"file\" name=\"urls_file\" accept=\".txt\" />
                                    <input type=\"text\" name=\"required_region\" value=\"北京\" placeholder=\"目标区域\" />
                                    <label style=\"display:flex;align-items:center;gap:8px;\"><input type=\"checkbox\" name=\"strict_region\" checked />仅保留目标区域企业数据</label>
                                    <select name=\"engine\">
                                        <option value=\"auto\">自动（优先浏览器渲染，失败回退）</option>
                                        <option value=\"playwright\">浏览器渲染</option>
                                        <option value=\"standard\">标准库抓取</option>
                                    </select>
                                    <button type=\"submit\">批量抓取并记录</button>
                                </form>
                                <hr style=\"margin:16px 0;border:none;border-top:1px solid #eee;\" />
                                <h3>智能发现可抓取网址（北京）</h3>
                                <form method=\"post\" action=\"/crawl/discover\">
                                    <textarea name=\"candidate_targets\" rows=\"4\" placeholder=\"候选网址（可留空使用内置源）\"></textarea>
                                    <input type=\"text\" name=\"required_region\" value=\"北京\" placeholder=\"目标区域\" />
                                    <label style=\"display:flex;align-items:center;gap:8px;\"><input type=\"checkbox\" name=\"strict_region\" checked />仅接受目标区域结果</label>
                                    <input type=\"number\" min=\"1\" max=\"10\" name=\"min_score\" value=\"4\" placeholder=\"最低可用评分\" />
                                    <select name=\"engine\">
                                        <option value=\"standard\">标准库抓取</option>
                                        <option value=\"auto\">自动（优先浏览器渲染）</option>
                                        <option value=\"playwright\">浏览器渲染</option>
                                    </select>
                                    <label style=\"display:flex;align-items:center;gap:8px;\"><input type=\"checkbox\" name=\"crawl_after_discovery\" checked />发现后立即抓取一轮</label>
                                    <button type=\"submit\">分析并追加可用网址</button>
                                </form>
                            </div>

                            <div class=\"card\">
                                <h2>目标网址健康度</h2>
                                <form method="post" action="/crawl/prune-paused" style="max-width:280px;margin-bottom:10px;">
                                    <button type="submit">一键清理已暂停目标</button>
                                </form>
                                <form method="post" action="/crawl/revive-paused" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:10px;">
                                    <input type="text" name="required_region" value="北京" placeholder="目标区域" />
                                    <input type="number" min="1" max="10" name="min_score" value="4" placeholder="最低恢复评分" />
                                    <label style="display:flex;align-items:center;gap:8px;"><input type="checkbox" name="strict_region" checked />严格区域</label>
                                    <button type="submit">复检并恢复暂停目标</button>
                                </form>
                                <table><thead><tr><th>URL</th><th>成功</th><th>失败</th><th>连续失败</th><th>过滤</th><th>均分</th><th>暂停</th><th>暂停原因</th><th>最近状态</th></tr></thead><tbody>{target_rows}</tbody></table>
                            </div>

                            <div class=\"card\">
                                <h2>后台抓取状态</h2>
                                <p>最近一轮：成功 {latest_cycle['processed']}，失败 {latest_cycle['failed']}，总计 {latest_cycle['total']}</p>
                                <form method=\"post\" action=\"/crawler/toggle\" style=\"max-width:260px;\"><button type=\"submit\">{crawler_button_label}</button></form>
                            </div>

                            <div class=\"card\"><h2>抓取企业资料</h2>
                                <form method=\"post\" action=\"/company-profiles/clear-history\" style=\"max-width:320px;margin-bottom:10px;\">
                                    <button type=\"submit\" onclick=\"return confirm('确认清理全部历史企业资料吗？此操作不可恢复。')\">清理历史企业资料</button>
                                </form>
                                <form method=\"get\" action=\"/\"><div style=\"display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;\">
                                        <input name=\"company_name\" placeholder=\"企业名称\" value=\"{html.escape(company_filters['company_name'])}\" />
                                        <input name=\"industry\" placeholder=\"行业\" value=\"{html.escape(company_filters['industry'])}\" />
                                        <input name=\"region\" placeholder=\"区域\" value=\"{html.escape(company_filters['region'])}\" />
                                        <input name=\"status\" placeholder=\"状态\" value=\"{html.escape(company_filters['status'])}\" />
                                        <button type=\"submit\">筛选</button>
                                </div></form>
                                <table><thead><tr><th>企业</th><th>联系人</th><th>电话</th><th>邮箱</th><th>办公地址</th><th>行业</th><th>区域</th><th>状态</th></tr></thead><tbody>{company_rows}</tbody></table>
                            </div>
                            <div class=\"card\"><h2>用户与角色</h2><table><thead><tr><th>用户名</th><th>角色</th><th>创建时间</th></tr></thead><tbody>{user_rows}</tbody></table></div>
                            <div class=\"card\"><h2>操作日志</h2><table><thead><tr><th>动作</th><th>详情</th><th>时间</th></tr></thead><tbody>{activity_rows}</tbody></table></div>
                        </div>
                    </body>
                </html>
                """

    def _render_company_detail(self, profile_id):
        profile = store.get_company_profile(profile_id)
        if not profile:
            return "<h2>未找到企业资料</h2><p><a href='/'>返回首页</a></p>"
        fields = [
            ("企业名称", profile.get("company_name") or "-"),
            ("联系人", profile.get("contact_name") or "-"),
            ("电话", profile.get("phone") or "-"),
            ("邮箱", profile.get("email") or "-"),
            ("办公地址", profile.get("address") or "-"),
            ("行业", profile.get("industry") or "-"),
            ("区域", profile.get("region") or "-"),
            ("抓取链接", profile.get("url") or "-"),
        ]
        rows = "".join(f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>" for label, value in fields)
        link_html = ""
        if profile.get("url"):
            link_html = f'<p><a href="{html.escape(str(profile.get("url")))}" target="_blank" rel="noopener">打开原始页面</a></p>'
        form_fields = "".join(
            f'<label>{label}<input name="{name}" value="{html.escape(str(value or ""))}" /></label>'
            for name, label, value in [
                ("company_name", "企业名称", profile.get("company_name")),
                ("contact_name", "联系人", profile.get("contact_name")),
                ("phone", "电话", profile.get("phone")),
                ("email", "邮箱", profile.get("email")),
                ("address", "办公地址", profile.get("address")),
                ("industry", "行业", profile.get("industry")),
                ("region", "区域", profile.get("region")),
                ("url", "抓取链接", profile.get("url")),
            ]
        )
        return f"""
        <!doctype html>
        <html lang=\"zh-CN\">
          <head><meta charset=\"utf-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /><title>企业资料详情</title>
          <style>body{{font-family:Arial,sans-serif;background:#f5f7fb;padding:24px;}} .card{{background:#fff;padding:24px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.06);max-width:760px;margin:0 auto;}} .header{{display:flex;justify-content:space-between;align-items:center;gap:12px;}} table{{width:100%;border-collapse:collapse;}} th,td{{padding:10px;border-bottom:1px solid #eee;text-align:left;}} a{{color:#2563eb;text-decoration:none;}} a:hover{{text-decoration:underline;}} form{{display:grid;gap:10px;margin-top:12px;}} label{{display:grid;gap:6px;font-weight:600;}} input{{padding:10px;border:1px solid #ddd;border-radius:8px;}} button{{background:#2563eb;color:#fff;border:none;padding:10px 14px;border-radius:8px;cursor:pointer;}}</style></head>
          <body><div class=\"card\"><div class=\"header\"><h2>企业资料详情</h2><a href=\"/\">返回控制台</a></div>{link_html}<table>{rows}</table><form method=\"post\" action=\"/company/{profile_id}/edit\"><h3>编辑企业资料</h3>{form_fields}<button type=\"submit\">保存修改</button></form></div></body></html>
        """

    def _build_bar_chart(self, data, title):
        if not data:
            return f"<div><strong>{html.escape(title)}</strong><p>暂无数据</p></div>"
        max_value = max(data.values()) if data else 0
        rows = []
        for label, value in sorted(data.items()):
            width = 0 if max_value == 0 else int(value * 100 / max_value)
            rows.append(
                f"<div class=\"bar-row\"><div style=\"min-width: 80px;\">{html.escape(str(label))}</div><div class=\"bar\"><span style=\"width: {width}%\"></span></div><div>{value}</div></div>"
            )
        return f"<div><strong>{html.escape(title)}</strong><div class=\"bar-chart\">{' '.join(rows)}</div></div>"

    def _parse_form_data(self):
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            environ = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type}
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ)
            params = {}
            for key in form.keys():
                item = form[key]
                if item.filename:
                    value = item.file.read().decode("utf-8", errors="ignore")
                else:
                    value = item.value
                params[key] = [value]
            return params

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body, keep_blank_values=True)

    def _get_first(self, params, key, default=""):
        values = params.get(key, [])
        return values[0] if values else default

    def _get_query_param(self, key):
        parsed = urlparse(self.path)
        values = parse_qs(parsed.query).get(key, [])
        return values[0] if values else ""

    def _is_authenticated(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            if part.strip().startswith("session_id="):
                session_id = part.split("=", 1)[1].strip()
                return self._session_store().get(session_id) is not None
        return False

    def _current_user(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            if part.strip().startswith("session_id="):
                session_id = part.split("=", 1)[1].strip()
                return self._session_store().get(session_id)
        return None

    def _set_session(self, session_id, user):
        self._session_store()[session_id] = user

    def _clear_session(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            if part.strip().startswith("session_id="):
                session_id = part.split("=", 1)[1].strip()
                self._session_store().pop(session_id, None)

    def _session_store(self):
        if not hasattr(self.server, "session_store"):
            self.server.session_store = {}
        return self.server.session_store

    def _require_role(self, allowed_roles):
        user = self._current_user()
        if not user or user.get("role") not in allowed_roles:
            self._send_text(403, "Forbidden")
            raise PermissionError("forbidden")

    def _redirect(self, path):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def _send_html(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send_text(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send_csv(self, payload):
        output = ["name,email,status\n"]
        for row in payload.get("leads", []):
            output.append(f"{row.get('name','')},{row.get('email','')},{row.get('status','')}\n")
        body = "".join(output)
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send_company_csv(self, payload):
        output = ["company_name,contact_name,phone,email,address,industry,region,status\n"]
        for row in payload.get("company_profiles", []):
            output.append(
                f"{row.get('company_name','')},{row.get('contact_name','')},{row.get('phone','')},{row.get('email','')},{row.get('address','')},{row.get('industry','')},{row.get('region','')},{row.get('status','')}\n"
            )
        body = "".join(output)
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    configured_port = os.getenv("PORT", "6000")
    allow_port_fallback = os.getenv("CRM_ALLOW_PORT_FALLBACK", "0").lower() in {"1", "true", "yes", "on"}
    try:
        preferred_port = int(configured_port)
    except ValueError:
        preferred_port = 6000

    candidate_ports = [preferred_port]
    if allow_port_fallback:
        candidate_ports.extend([preferred_port + 1, 6000, 6001, 8080, 8081, 8000, 8001, 8002])
    server = None
    last_error = None
    for port in candidate_ports:
        try:
            server = HTTPServer((host, port), CRMHandler)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise last_error
    if server.server_address[1] != preferred_port:
        print(
            f"Warning: server started on fallback port {server.server_address[1]} (preferred: {preferred_port})",
            flush=True,
        )
    print(f"Server started at http://{host}:{server.server_address[1]}")
    server.serve_forever()
