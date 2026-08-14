# 部署目录说明

本目录提供生产部署所需的最小文件集：

- install_server.sh: 一键部署脚本（安装依赖、初始化数据库、配置 systemd 与 Nginx）
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

## 重要说明

- 项目强依赖 PostgreSQL，必须设置 CRM_POSTGRES_DSN
- systemd 服务默认监听端口 8888
- Nginx 配置默认 proxy_pass 到 127.0.0.1:8888

详细架构、API、运维与排障文档请查看仓库根目录 README。
