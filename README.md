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
   - export PORT=6000
   - export HOST=0.0.0.0

4. 清理旧数据并重新初始化
   - psql "postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   - CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local' PORT=6000 .venv/bin/python -c "from app import DatabaseStore; DatabaseStore().init_db()"

5. 运行原有 Web 应用
   - CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local' HOST=0.0.0.0 PORT=6000 .venv/bin/python server.py

5. 浏览器访问
   - http://127.0.0.1:6000/

6. 运行 FastAPI 服务
   - CRM_POSTGRES_DSN='postgresql://yangchuan:postgres@127.0.0.1:5432/crm_local' PORT=6000 .venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 6000

7. 运行 Scrapy 爬虫
   - cd scrapy_project
   - scrapy crawl company_spider -a urls="https://example.com,https://www.baidu.com"

8. 启动 Celery worker
   - CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 celery -A celery_app worker --loglevel=info

9. 使用 Docker Compose
   - docker compose up --build

## 服务器部署（详细步骤）

下面是将项目部署到 Linux 服务器并稳定运行的完整流程，默认使用 PostgreSQL 作为主数据库，并通过 Nginx + systemd 提供外部访问。

### 1. 服务器准备

#### 1.1 安装依赖
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv nginx postgresql postgresql-contrib git curl
```

#### 1.2 创建 PostgreSQL 数据库与用户
```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE crm_prod;
CREATE USER crm_app WITH PASSWORD 'your-strong-password';
ALTER ROLE crm_app SET client_encoding TO 'utf8';
ALTER ROLE crm_app SET default_transaction_isolation TO 'read committed';
ALTER ROLE crm_app SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE crm_prod TO crm_app;
SQL
```

如果数据库监听地址不是本机，请确认 PostgreSQL 的 `pg_hba.conf` 与 `postgresql.conf` 已允许 `127.0.0.1` 访问。

### 2. 部署代码

```bash
sudo mkdir -p /opt/crm_project
sudo chown -R $USER:$USER /opt/crm_project
cd /opt/crm_project

git clone <your-repo-url> .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量

建议将环境变量写入系统环境文件，避免每次手动导出：

```bash
sudo tee /etc/environment.d/crm.conf >/dev/null <<'EOF'
CRM_POSTGRES_DSN=postgresql://crm_app:your-strong-password@127.0.0.1:5432/crm_prod
HOST=0.0.0.0
PORT=8888
EOF
```

然后刷新环境：

```bash
source /etc/environment
```

> 注意：项目已改为强制使用 PostgreSQL；如果没有设置 `CRM_POSTGRES_DSN`，服务会直接报错。

### 4. 初始化数据库

```bash
cd /opt/crm_project
source .venv/bin/activate
CRM_POSTGRES_DSN='postgresql://crm_app:your-strong-password@127.0.0.1:5432/crm_prod' \
.venv/bin/python -c "from app import DatabaseStore; DatabaseStore(None).init_db()"
```

### 5. 直接启动服务

```bash
cd /opt/crm_project
source .venv/bin/activate
CRM_POSTGRES_DSN='postgresql://crm_app:your-strong-password@127.0.0.1:5432/crm_prod' \
HOST=0.0.0.0 PORT=8888 .venv/bin/python server.py
```

启动后可通过以下地址验证：

```bash
curl http://127.0.0.1:8888/login
```

### 6. 使用 systemd 管理服务

复制示例服务文件：

```bash
sudo cp deploy/systemd-crm-crawler.service /etc/systemd/system/crm-crawler.service
sudo systemctl daemon-reload
sudo systemctl enable crm-crawler.service
sudo systemctl start crm-crawler.service
```

检查状态：

```bash
sudo systemctl status crm-crawler.service
sudo journalctl -u crm-crawler.service -n 100 --no-pager
```

### 7. 配置 Nginx 反向代理

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/crm.conf
sudo nginx -t
sudo systemctl reload nginx
```

示例访问地址：

```bash
http://your-server-domain-or-ip/
```

### 8. 防火墙与安全建议

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

生产环境建议同时配置：
- HTTPS 证书（例如 Let's Encrypt）
- 定期备份 PostgreSQL 数据库
- 将抓取任务改为由 Celery / Redis 队列异步执行

### 9. 一键部署脚本（可直接复制到服务器执行）

如果你希望一条龙部署，可以直接在服务器上执行下面的脚本：

```bash
scp -r /path/to/this/project user@your-server:/tmp/crm_project
ssh user@your-server
sudo cp -r /tmp/crm_project /opt/crm_project
sudo chmod +x /opt/crm_project/deploy/install_server.sh
sudo SOURCE_DIR=/opt/crm_project /opt/crm_project/deploy/install_server.sh
```

脚本会自动完成以下操作：
- 安装 Python / PostgreSQL / Nginx / Git 依赖
- 创建数据库与数据库用户
- 拉取项目代码并安装依赖
- 初始化 PostgreSQL 表结构
- 配置 systemd 服务与 Nginx 反向代理

### 10. 常见排障

- 如果启动时报 `CRM_POSTGRES_DSN must be set`：确认环境变量已正确设置。
- 如果数据库连接失败：确认 PostgreSQL 是否监听 `127.0.0.1:5432`，并且用户密码、数据库名正确。
- 如果访问不到页面：确认 `HOST=0.0.0.0` 且 `PORT=8888` 已生效，并检查 `systemctl status` 与 `nginx` 配置。

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
