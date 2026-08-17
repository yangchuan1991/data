#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-crm-crawler.service}"
APP_DIR="${APP_DIR:-/opt/crm_project}"
ENV_FILE="${ENV_FILE:-/etc/environment.d/crm.conf}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8888}"
PYTHON_BIN="${PYTHON_BIN:-${APP_DIR}/.venv/bin/python}"

echo "[1/8] Service status"
sudo systemctl --no-pager --full status "${SERVICE_NAME}" | sed -n '1,30p' || true

echo
echo "[2/8] Recent service logs"
sudo journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true

echo
echo "[3/8] Environment file"
if [[ -f "${ENV_FILE}" ]]; then
  sudo grep -E '^(CRM_POSTGRES_DSN|HOST|PORT|CRM_ALLOW_PORT_FALLBACK)=' "${ENV_FILE}" || true
else
  echo "Missing: ${ENV_FILE}"
fi

echo
echo "[4/8] Runtime listener check"
sudo ss -lntp | grep -E ":(${PORT}|6000|6001|8000|8001|8080|8081)\\b" || true

echo
echo "[5/8] Nginx upstream config"
sudo nginx -t || true
sudo grep -R "proxy_pass" /etc/nginx/conf.d /etc/nginx/sites-enabled 2>/dev/null || true

echo
echo "[6/8] DB connectivity"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi
if [[ -n "${CRM_POSTGRES_DSN:-}" ]]; then
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Python runtime not found: ${PYTHON_BIN}"
  else
    "${PYTHON_BIN}" - <<'PY'
import os
import psycopg2

dsn = os.environ.get("CRM_POSTGRES_DSN")
try:
    with psycopg2.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("select now()")
            print("DB ok:", cur.fetchone()[0])
except Exception as exc:
    print("DB failed:", exc)
PY
  fi
else
  echo "CRM_POSTGRES_DSN is empty"
fi

echo
echo "[7/8] Code signature check"
if [[ -f "${APP_DIR}/server.py" ]]; then
  grep -n "company-profiles/clear-history" "${APP_DIR}/server.py" || true
  grep -n "CRM_ALLOW_PORT_FALLBACK" "${APP_DIR}/server.py" || true
else
  echo "Missing: ${APP_DIR}/server.py"
fi

echo
echo "[8/8] Local HTTP check"
curl -sS -m 5 -I "http://${HOST}:${PORT}/login" || true

echo
echo "Diagnosis finished."