#!/usr/bin/env sh
set -eu

mkdir -p "${APP_CONFIG_DIR}" "${ONEDRIVE_DATA_DIR}"
chown "${PUID}:${PGID}" "${APP_CONFIG_DIR}" "${ONEDRIVE_DATA_DIR}"
chmod 777 "${APP_CONFIG_DIR}" "${ONEDRIVE_DATA_DIR}"
umask 000

# Reverse proxies commonly terminate TLS before forwarding to Uvicorn. Trust
# forwarded protocol headers only from explicitly configured proxy networks so
# the management API keeps same-origin protection without misreading HTTPS.
forwarded_allow_ips="${ONESYNC_FORWARDED_ALLOW_IPS:-127.0.0.1,::1,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10}"

exec setpriv \
    --reuid="${PUID}" \
    --regid="${PGID}" \
    --clear-groups \
    python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8098}" \
    --proxy-headers \
    --forwarded-allow-ips "${forwarded_allow_ips}"
