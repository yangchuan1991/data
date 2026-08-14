#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/crm_project}"
SERVICE_NAME="${SERVICE_NAME:-crm-crawler.service}"
ENV_FILE="${ENV_FILE:-/etc/environment.d/crm.conf}"
SOURCE_DIR="${SOURCE_DIR:-}"
BRANCH="${BRANCH:-main}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root, for example: sudo APP_DIR=${APP_DIR} bash deploy/restart_server.sh"
  exit 1
fi

echo "[1/7] Ensuring project directory exists..."
mkdir -p "${APP_DIR}"

echo "[2/7] Updating project code..."
if [[ -n "${SOURCE_DIR}" ]]; then
  if [[ ! -d "${SOURCE_DIR}" ]]; then
    echo "SOURCE_DIR not found: ${SOURCE_DIR}"
    exit 1
  fi

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.venv' \
      --exclude '__pycache__' \
      --exclude '.pytest_cache' \
      "${SOURCE_DIR}/" "${APP_DIR}/"
  else
    echo "rsync not found, using cp -a fallback (stale files may remain)."
    cp -a "${SOURCE_DIR}/." "${APP_DIR}/"
  fi
elif [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --all --prune
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
else
  echo "No SOURCE_DIR provided and ${APP_DIR} is not a git repo."
  echo "Set SOURCE_DIR to your updated code path and run again."
  exit 1
fi

echo "[3/7] Preparing python environment..."
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

echo "[4/7] Loading runtime environment..."
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -z "${CRM_POSTGRES_DSN:-}" ]]; then
  echo "CRM_POSTGRES_DSN is empty. Set it in ${ENV_FILE} or export before running this script."
  exit 1
fi

echo "[5/7] Initializing database schema..."
CRM_POSTGRES_DSN="${CRM_POSTGRES_DSN}" "${APP_DIR}/.venv/bin/python" -c "from app import DatabaseStore; DatabaseStore(None).init_db()"

echo "[6/7] Reloading service and nginx config..."
if [[ -f "${APP_DIR}/deploy/systemd-crm-crawler.service" ]]; then
  install -m 0644 "${APP_DIR}/deploy/systemd-crm-crawler.service" "/etc/systemd/system/${SERVICE_NAME}"
fi
if [[ -f "${APP_DIR}/deploy/nginx.conf" ]]; then
  install -m 0644 "${APP_DIR}/deploy/nginx.conf" "/etc/nginx/conf.d/crm.conf"
fi

chown -R www-data:www-data "${APP_DIR}" || true
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true
systemctl restart "${SERVICE_NAME}"
nginx -t
systemctl reload nginx

echo "[7/7] Verifying service status..."
systemctl --no-pager --full status "${SERVICE_NAME}" | sed -n '1,20p'
journalctl -u "${SERVICE_NAME}" -n 30 --no-pager

echo "Done. Updated code is deployed and ${SERVICE_NAME} has been restarted."