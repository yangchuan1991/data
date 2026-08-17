# 部署目录说明

本目录提供生产部署所需的最小文件集：

- install_server.sh: 一键部署脚本（安装依赖、初始化数据库、配置 systemd 与 Nginx）
- restart_server.sh: 一键更新并重启脚本（同步新代码、安装依赖、重启服务）
- systemd-crm-crawler.service: systemd 服务模板
- nginx.conf: Nginx 反向代理模板（默认转发到 127.0.0.1:8888）

## 快速部署

```bash
sudo cp -r /path/to/project /opt/crm_project
sudo chmod +x /opt/crm_project/deploy/install_server.sh
sudo SOURCE_DIR=/opt/crm_project /opt/crm_project/deploy/install_server.sh
```

## 部署后检查

```bash
sudo systemctl status crm-crawler.service
sudo journalctl -u crm-crawler.service -n 200 --no-pager
sudo nginx -t
sudo systemctl reload nginx
```

## 一键诊断停机原因

```bash
sudo chmod +x /opt/crm_project/deploy/diagnose_server.sh
sudo APP_DIR=/opt/crm_project /opt/crm_project/deploy/diagnose_server.sh
```

该脚本会检查：

- systemd 服务状态与最近日志
- 环境变量是否正确加载（CRM_POSTGRES_DSN / HOST / PORT）
- 应用监听端口与 Nginx upstream 一致性
- PostgreSQL 连接可用性
- 当前代码是否已包含最新修复标记

## 一键更新并重启（推荐日常发版）

首次给执行权限：

```bash
sudo chmod +x /opt/crm_project/deploy/restart_server.sh
```

方式 A：服务器项目目录本身是 git 仓库（默认拉取 main 分支）

```bash
sudo APP_DIR=/opt/crm_project BRANCH=main /opt/crm_project/deploy/restart_server.sh
```

方式 B：从指定源码目录同步到 /opt/crm_project 后重启

```bash
sudo APP_DIR=/opt/crm_project SOURCE_DIR=/path/to/updated/project /opt/crm_project/deploy/restart_server.sh
```

脚本会自动执行：

- 更新代码（git pull 或 SOURCE_DIR 同步）
- 安装/更新 Python 依赖
- 使用 CRM_POSTGRES_DSN 初始化数据库表结构
- 重启 systemd 服务并 reload Nginx
- 输出服务状态与最近日志

## 重要说明

- 项目强依赖 PostgreSQL，必须设置 CRM_POSTGRES_DSN
- systemd 服务默认监听端口 8888
- Nginx 配置默认 proxy_pass 到 127.0.0.1:8888
- 生产环境默认不允许端口自动回退，端口被占用会直接启动失败并写入日志（避免服务跑在错误端口导致 502）
- 如需临时开启端口回退，可设置环境变量 CRM_ALLOW_PORT_FALLBACK=1（仅建议开发排障时使用）

详细架构、API、运维与排障文档请查看仓库根目录 README。
