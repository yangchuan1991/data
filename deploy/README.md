# 企业级部署说明

## 1. 目标
将当前获客系统从自定义脚本抓取升级为基于 Scrapy 的正式爬虫项目，并提供可部署到服务器的目录结构与运行方式。

## 2. 项目结构
- app.py：业务与数据库层
- server.py：后台管理页面
- scrapy_project/：Scrapy 爬虫工程
  - scrapy.cfg：Scrapy 配置入口
  - crawler/：spiders / items / pipelines / settings

## 3. 依赖
建议使用 Python 3.11+，并安装以下依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install scrapy
```

## 4. 运行方式
### 启动 Web 后台
```bash
python3 server.py
```

### 运行 Scrapy 爬虫
```bash
cd scrapy_project
scrapy crawl company_spider -a urls="https://example.com,https://www.baidu.com" -s CRAWLER_DB_PATH=../data.db
```

## 5. 服务器部署建议
- 使用 systemd / supervisor 管理后台进程
- 将数据库文件放在持久化目录
- 将日志输出重定向到文件
- 对外提供反向代理，例如 Nginx + Gunicorn/uwsgi（若后续扩展为 Web API）

## 6. 企业级增强建议
- 将抓取任务改造成消息队列任务（Celery/RQ）
- 增加代理池、去重、失败重试与调度策略
- 增加监控与告警
- 将爬虫结果落入 Elasticsearch / PostgreSQL
