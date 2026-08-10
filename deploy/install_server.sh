#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/crm_project"
DB_NAME="crm_prod"
DB_USER="crm_app"
DB_PASSWORD="your-strong-password"
PORT="8888"
HOST="0.0.0.0"
POSTGRES_DSN="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"
SOURCE_DIR="${SOURCE_DIR:-$(pwd)}"

echo "[1/8] Updating system packages..."
sudo apt update
sudo apt install -y python3-pip python3-venv nginx postgresql postgresql-contrib git curl

echo "[2/8] Creating PostgreSQL database and user..."
sudo -u postgres psql <<SQL
CREATE DATABASE ${DB_NAME};
DO \$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$;
ALTER ROLE ${DB_USER} SET client_encoding TO 'utf8';
ALTER ROLE ${DB_USER} SET default_transaction_isolation TO 'read committed';
ALTER ROLE ${DB_USER} SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

echo "[3/8] Preparing project directory..."
sudo mkdir -p "${APP_DIR}"
sudo chown -R "$USER:$USER" "${APP_DIR}"

if [ -d "${SOURCE_DIR}/.git" ]; then
  echo "Copying project from ${SOURCE_DIR} to ${APP_DIR}..."
  sudo rm -rf "${APP_DIR}"
  sudo mkdir -p "${APP_DIR}"
  sudo cp -a "${SOURCE_DIR}/." "${APP_DIR}/"
  sudo chown -R "$USER:$USER" "${APP_DIR}"
else
  echo "Source directory ${SOURCE_DIR} is not a git repo. Please provide a valid project directory."
  exit 1
fi

echo "[4/8] Creating Python virtualenv and installing dependencies..."
cd "${APP_DIR}"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

echo "[5/8] Initializing database schema..."
CRM_POSTGRES_DSN="${POSTGRES_DSN}" \
./.venv/bin/python -c "from app import DatabaseStore; DatabaseStore(None).init_db()"

echo "[6/8] Writing environment config..."
sudo tee /etc/environment.d/crm.conf >/dev/null <<EOF
CRM_POSTGRES_DSN=${POSTGRES_DSN}
HOST=${HOST}
PORT=${PORT}
EOF

source /etc/environment 2>/dev/null || true

echo "[7/8] Installing systemd service and nginx config..."
sudo cp deploy/systemd-crm-crawler.service /etc/systemd/system/crm-crawler.service
sudo cp deploy/nginx.conf /etc/nginx/conf.d/crm.conf
sudo systemctl daemon-reload
sudo systemctl enable crm-crawler.service
sudo systemctl restart crm-crawler.service
sudo nginx -t
sudo systemctl reload nginx

echo "[8/8] Deployment complete."
echo "Open: http://your-server-ip/"
echo "Check service: sudo systemctl status crm-crawler.service"
