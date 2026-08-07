# 获客系统项目

这是一个已经升级为更接近企业级的获客系统，包含以下能力：

- 爬虫能力：已接入 Scrapy 工程化爬虫结构，支持按目标 URL 执行抓取并将结果写入数据库
- 营销能力：支持创建营销活动、营销消息（邮件/短信）以及消息状态追踪
- 线索管理：可录入潜在客户信息并管理线索状态
- 数据分析与可视化：提供摘要指标、状态分布图表和操作日志
- 用户权限与角色：支持创建管理员、经理、观察者等角色用户

## 技术栈

- Python 3.11+
- PostgreSQL 16+
- Scrapy
- FastAPI / Uvicorn
- Celery / Redis
- 标准库 HTTP Server

## 项目结构

- app.py: 数据层、爬虫解析逻辑、分析与权限逻辑
- server.py: 本地 Web 服务与页面渲染
- scrapy_project/: Scrapy 工程目录
  - scrapy.cfg: Scrapy 配置入口
  - crawler/: spiders / items / pipelines / settings
- tests/test_app.py: 单元测试
- requirements.txt: 依赖说明
- deploy/: 部署说明与服务器配置示例

## 快速开始

1. 创建虚拟环境
   - python3 -m venv .venv
   - source .venv/bin/activate

2. 安装依赖
   - pip install -r requirements.txt

3. 配置 PostgreSQL 环境变量
   - export CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local'
   - export PORT=8000

4. 清理旧数据并重新初始化
   - psql "postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   - CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local' PORT=8000 .venv/bin/python -c "from app import DatabaseStore; DatabaseStore().init_db()"

5. 运行原有 Web 应用
   - CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local' PORT=8000 .venv/bin/python server.py

5. 浏览器访问
   - http://127.0.0.1:8000/

6. 运行 FastAPI 服务
   - CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local' PORT=8000 .venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 8000

7. 运行 Scrapy 爬虫
   - cd scrapy_project
   - scrapy crawl company_spider -a urls="https://example.com,https://www.baidu.com"

8. 启动 Celery worker
   - CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 celery -A celery_app worker --loglevel=info

9. 使用 Docker Compose
   - docker compose up --build

## 服务器部署

请参考 [deploy/README.md](deploy/README.md) 中的完整步骤。核心要点如下：

- 使用 PostgreSQL 作为主数据库
- 通过 systemd 管理服务进程
- 使用 Nginx 反向代理到本地 8000 端口
- 将 CRM_POSTGRES_DSN 和 PORT 配置为系统环境变量
- 服务启动前必须保证 PostgreSQL 实例可达，且数据库用户具备建表与写入权限

## 当前已实现功能

- 图表分析：线索状态、渠道分布、营销消息状态的可视化条形图
- Scrapy 工程化结构：已建立独立爬虫项目目录，包含 Spider / Item / Pipeline / Settings
- 企业级部署文档：提供 systemd 与 Nginx 配置示例
- 邮件/短信营销：支持创建营销消息并记录发送目标人数与状态
- 用户权限与角色：支持创建不同角色用户并记录到数据库

## 已完成的企业级增强

- FastAPI 健康检查与指标接口
- Celery/Redis 任务队列接入
- PostgreSQL 适配层与 Docker Compose 部署模板
- 结构化日志与日志轮转
- 可通过 API 提交抓取任务并记录监控事件

## 后续可扩展方向

- 增加代理池、失败重试与去重策略
- 接入 Sentry / Prometheus / Grafana
- 将结果落入 PostgreSQL / Elasticsearch
