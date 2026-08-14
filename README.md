# 北京企业获客抓取系统

本项目是一个面向北京地区企业数据采集与后台管理的获客系统，包含：

- 企业网页抓取与结构化提取
- 后台仅保留可用企业资料（不记录爬虫任务明细）
- 抓取目标自动发现、评分、追加
- 抓取目标健康度管理（自动暂停、复检恢复、清理）
- 后台可视化管理（抓取、企业资料、日志）
- API 与 Celery 支持（便于集成）

## 1. 当前状态（可部署性结论）

已完成基础可部署检查并修复关键阻断项：

- 已修复 Nginx 反向代理端口冲突（改为 8888）
- 已修复 Docker Compose 与 PostgreSQL 强依赖不一致问题（增加 postgres 服务与 DSN）
- 已统一部署文档端口与环境变量口径

本仓库当前可以部署到服务器（前提：目标机满足 Python、PostgreSQL、Nginx、systemd 等依赖）。

## 2. 核心能力

### 2.1 抓取与提取

- 支持标准库抓取 / Playwright 渲染抓取
- 自动抽取字段：
  - company_name
  - contact_name
  - phone
  - email
  - address
  - industry
  - region
- 支持北京区域严格过滤，降低脏数据
- 抓取流程默认仅沉淀可用企业资料，不再写入 crawl_jobs 任务明细

### 2.2 目标发现与提效

- 智能发现可抓取网址（支持评分阈值）
- 可用网址自动追加到目标池
- 发现后可立即触发首轮抓取

### 2.3 目标健康度治理

- 记录每个目标网址：成功/失败/过滤/平均分/连续失败
- 自动暂停低质量目标（连续失败或成功率过低）
- 后台与 API 支持：
  - 一键清理已暂停目标
  - 复检并恢复暂停目标

## 3. 技术栈

- Python 3.11+
- PostgreSQL 16+
- FastAPI + Uvicorn
- Celery + Redis
- Scrapy
- Nginx + systemd

## 4. 目录说明

- app.py: 核心业务逻辑、数据存储、抓取流程、目标健康治理
- server.py: 后台 Web 管理界面（HTTPServer）
- api.py: FastAPI 接口
- celery_app.py: Celery 任务入口
- scrapy_project/: Scrapy 工程
- deploy/: 部署脚本与示例配置

## 5. 环境变量

必需：

- CRM_POSTGRES_DSN

常用：

- HOST（默认 0.0.0.0）
- PORT（推荐 8888）
- CRM_CRAWL_REQUIRED_REGION（默认 北京）
- CRM_CRAWL_STRICT_REGION（默认 1）

目标健康策略：

- CRM_TARGET_FAILURE_STREAK（默认 3）
- CRM_TARGET_MIN_SAMPLES（默认 5）
- CRM_TARGET_MIN_SUCCESS_RATE（默认 0.2）

## 6. 本地启动

### 6.1 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 6.2 配置数据库

```bash
export CRM_POSTGRES_DSN='postgresql://crm_app:your-password@127.0.0.1:5432/crm_local'
export HOST=0.0.0.0
export PORT=8888
```

### 6.3 初始化数据库

```bash
CRM_POSTGRES_DSN='postgresql://crm_app:your-password@127.0.0.1:5432/crm_local' \
.venv/bin/python -c "from app import DatabaseStore; DatabaseStore(None).init_db()"
```

### 6.4 启动后台服务

```bash
CRM_POSTGRES_DSN='postgresql://crm_app:your-password@127.0.0.1:5432/crm_local' \
HOST=0.0.0.0 PORT=8888 .venv/bin/python server.py
```

访问：

- http://127.0.0.1:8888/login

默认账号：

- admin / admin123

## 7. API 清单（关键）

- POST /api/crawl
  - 提交抓取任务
- POST /api/crawl/discover
  - 发现可用网址并可选立即抓取
- POST /api/crawl/prune-paused
  - 清理已暂停目标
- POST /api/crawl/revive-paused
  - 复检并恢复暂停目标
- GET /healthz
- GET /metrics

## 8. 生产部署（推荐：systemd + Nginx）

### 8.1 一键部署（服务器）

```bash
sudo cp -r /path/to/project /opt/crm_project
sudo chmod +x /opt/crm_project/deploy/install_server.sh
sudo SOURCE_DIR=/opt/crm_project /opt/crm_project/deploy/install_server.sh
```

脚本会：

- 安装 Python / PostgreSQL / Nginx / Git / curl
- 创建数据库与用户
- 安装依赖并初始化表结构
- 写入环境变量到 /etc/environment.d/crm.conf
- 安装 systemd 服务
- 安装 Nginx 配置并重载

### 8.2 手工部署关键配置

systemd：

- 服务文件：deploy/systemd-crm-crawler.service
- 默认启动：/opt/crm_project/.venv/bin/python /opt/crm_project/server.py
- 默认端口：8888

Nginx：

- 配置文件：deploy/nginx.conf
- 反向代理：127.0.0.1:8888

### 8.3 常用运维命令

```bash
sudo systemctl status crm-crawler.service
sudo journalctl -u crm-crawler.service -n 200 --no-pager
sudo nginx -t
sudo systemctl reload nginx
```

## 9. Docker Compose（开发/演示）

已提供 postgres + redis + api + worker 组合，直接：

```bash
docker compose up --build
```

默认 API 端口：8000。

## 10. 部署前检查清单

- CRM_POSTGRES_DSN 指向可连通数据库
- postgres 用户拥有 schema/table 权限
- Nginx upstream 与应用监听端口一致（8888）
- 服务用户可读取项目目录与虚拟环境
- 80/443 防火墙规则已放行

## 11. 已知限制与建议

- 项目测试依赖外部 PostgreSQL；CI 建议通过容器注入测试数据库
- server.py 基于标准库 HTTPServer，生产可考虑迁移到 Gunicorn/Uvicorn 统一入口
- 建议接入 HTTPS、备份、告警和审计

## 12. 故障排查

- 报错 CRM_POSTGRES_DSN must be set
  - 检查 /etc/environment.d/crm.conf 是否生效
- 页面 502/无法访问
  - 检查 Nginx proxy_pass 与服务端口是否一致
- 抓取量低
  - 在后台执行“智能发现可抓取网址（北京）”
  - 查看“目标网址健康度”中的暂停原因并复检恢复
