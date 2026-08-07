# 企业级部署说明

## 1. 目标
将该获客系统部署到 Linux 服务器，并默认使用 PostgreSQL 作为持久化数据库。

## 2. 服务器要求
- Ubuntu / Debian / CentOS 7+
- Python 3.11+
- PostgreSQL 14+
- Nginx
- systemd

## 3. 服务端准备

### 3.1 安装依赖
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv nginx postgresql postgresql-contrib git
```

### 3.2 创建数据库
```bash
sudo -u postgres psql -c "CREATE DATABASE crm_prod;"
sudo -u postgres psql -c "CREATE USER crm_app WITH PASSWORD 'your-strong-password';"
sudo -u postgres psql -c "ALTER ROLE crm_app SET client_encoding TO 'utf8';"
sudo -u postgres psql -c "ALTER ROLE crm_app SET default_transaction_isolation TO 'read committed';"
sudo -u postgres psql -c "ALTER ROLE crm_app SET timezone TO 'UTC';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE crm_prod TO crm_app;"
```

## 4. 部署项目

### 4.1 上传代码
```bash
sudo mkdir -p /opt/crm_project
sudo chown -R $USER:$USER /opt/crm_project
cd /opt/crm_project
git clone <your-repo-url> .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4.2 配置环境变量
```bash
export CRM_POSTGRES_DSN='postgresql://crm_app:your-strong-password@127.0.0.1:5432/crm_prod'
export PORT=8000
```

可将其写入系统环境文件，例如：
```bash
sudo tee /etc/environment.d/crm.conf >/dev/null <<'EOF'
CRM_POSTGRES_DSN=postgresql://crm_app:your-strong-password@127.0.0.1:5432/crm_prod
PORT=8000
EOF
```

## 5. 运行方式

### 5.1 启动 Web 服务
```bash
CRM_POSTGRES_DSN='postgresql://crm_app:your-strong-password@127.0.0.1:5432/crm_prod' PORT=8000 /opt/crm_project/.venv/bin/python /opt/crm_project/server.py
```

### 5.2 以 systemd 管理
```bash
sudo cp deploy/systemd-crm-crawler.service /etc/systemd/system/crm-crawler.service
sudo systemctl daemon-reload
sudo systemctl enable crm-crawler.service
sudo systemctl start crm-crawler.service
```

### 5.3 配置 Nginx 反向代理
```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/crm.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 6. 说明
- 项目已改为强制使用 PostgreSQL；未设置 CRM_POSTGRES_DSN 时服务会直接报错。
- server.py 会在启动时初始化数据库结构并启动后台抓取循环。
- 建议将日志输出到 /var/log/crm/ 下，便于排障。

## 7. 生产环境建议
- 使用 HTTPS 证书（Let's Encrypt）
- 配置防火墙允许 80/443 端口
- 定期备份 PostgreSQL 数据库
- 为抓取任务增加 Celery / Redis 任务队列
