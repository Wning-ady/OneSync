#!/usr/bin/env sh
set -eu

mkdir -p "${APP_CONFIG_DIR}" "${ONEDRIVE_DATA_DIR}"
chown "${PUID}:${PGID}" "${APP_CONFIG_DIR}" "${ONEDRIVE_DATA_DIR}"
chmod 777 "${APP_CONFIG_DIR}" "${ONEDRIVE_DATA_DIR}"
umask 000

exec setpriv \
    --reuid="${PUID}" \
    --regid="${PGID}" \
    --clear-groups \
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8098}"
