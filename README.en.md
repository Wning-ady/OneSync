<p align="center"><img src="docs/assets/onesync-logo.png" width="160" alt="OneSync logo"></p>

# OneSync

> Controlled selective Microsoft OneDrive sync for Unraid.

[简体中文](README.md) | [Issues](../../issues)

OneSync runs the maintained [`abraunegg/onedrive`](https://github.com/abraunegg/onedrive) client. Selected folders are real files on Unraid, not an rclone FUSE mount. Run a one-time sync when you want to upload local changes and download cloud changes.

## Highlights

- Selective sync from a browser folder tree.
- Separate device-code authorization for OneDrive engine and Microsoft Graph.
- Dry-run before confirmed resync after scope changes.
- Graph status verification: the UI periodically checks Microsoft Graph and distinguishes pending, unverified, and disconnected states instead of trusting an old token file.
- No forced overwrite or `--cleanup-local-files`.
- One-time sync by default. Continuous monitoring stays off.

## Deploy

Create a `.env` file in the Unraid Compose Manager project directory. Generate the admin token with `openssl rand -hex 24`; it must contain at least 16 characters. Never commit `.env`, the token, or `docker compose config` output.

```dotenv
ONESYNC_BIND_ADDRESS=192.168.2.21
ONESYNC_ADMIN_TOKEN=replace-with-a-random-value-of-at-least-16-characters
ONESYNC_ALLOWED_HOSTS=192.168.2.21,127.0.0.1,localhost
```

Then use:

```yaml
services:
  onesync:
    image: ${ONESYNC_IMAGE:-docker.io/waning/onesync:latest}
    container_name: onesync
    environment:
      PUID: "99"
      PGID: "100"
      TZ: Asia/Shanghai
      GRAPH_CLIENT_ID: replace-with-your-entra-client-id
      GRAPH_TENANT_ID: 5dldn8.onmicrosoft.com
      ONESYNC_ADMIN_TOKEN: ${ONESYNC_ADMIN_TOKEN:?Set a random admin token of at least 16 characters in .env}
      ONESYNC_ALLOWED_HOSTS: ${ONESYNC_ALLOWED_HOSTS:-192.168.2.21,127.0.0.1,localhost}
    ports:
      - "${ONESYNC_BIND_ADDRESS:-192.168.2.21}:8098:8098"
    volumes:
      - /mnt/user/appdata/onesync:/onedrive/conf
      - /mnt/user/onedrive:/onedrive/data
    restart: unless-stopped
```

Open `http://192.168.2.21:8098` and enter `ONESYNC_ADMIN_TOKEN`. The browser session is stored in an HttpOnly, SameSite cookie and must be established again after a container restart. The default port mapping listens only on the configured LAN address, not `0.0.0.0`; non-LAN Tailscale sources remain blocked.

For DockerMan, import `unraid/onesync.xml`, enter an admin token of at least 16 characters, and do not add a second Port entry for `8098`. The XML uses `ExtraParams` to bind `192.168.2.21:8098`. If the Unraid address differs, update that binding and `ONESYNC_ALLOWED_HOSTS` together. Keep a `DOCKER-USER` firewall rule that allows only the management LAN and rejects WAN, non-LAN Tailscale sources, and IPv6.

### Deployment rollback

Before an upgrade, back up `/mnt/user/appdata/onesync`, `/mnt/user/onedrive`, and the current XML or Compose files. For Compose, set `ONESYNC_IMAGE` in `.env` to the previous known-good version and run `docker compose up -d`. For DockerMan, restore the backed-up template or temporarily recreate with the previous image tag. Preserve the admin token, host allowlist, LAN-only binding, firewall policy, and both persistent directories during rollback.

## Microsoft Entra setup

Create a single-tenant public client. Enable public client flows. Add redirect URIs `http://127.0.0.1:53100/` and `https://login.microsoftonline.com/common/oauth2/nativeclient`. Grant delegated `Files.ReadWrite.All`, `User.Read`, and `offline_access`, then grant admin consent. Put Application (client) ID in `GRAPH_CLIENT_ID`. Do not use a client secret.

## First sync

1. Click **Sync once** and complete OneDrive device-code authorization from the log.
2. Click **Connect Graph** and complete the second device-code authorization.
3. Load folders, select scope, save, then run **Controlled resync**.
4. Resync performs dry-run first and remains stopped on completion. Click **Sync once** for later changes.

If the LAN page cannot use the Clipboard API, click the device code itself to select it and press `Ctrl+C` (or `⌘+C` on macOS).

## Storage and safety

- Data: `/mnt/user/onedrive`
- Private configuration and OAuth tokens: `/mnt/user/appdata/onesync`
- `sync_list` lives at `/onedrive/conf/sync_list`.
- Back up data and configuration before state recovery. Do not delete configuration databases to troubleshoot.

## Images

- `ghcr.io/wning-ady/onesync:latest`
- `docker.io/<DOCKERHUB_USERNAME>/onesync:latest`

GitHub Actions publishes GHCR on `main` or `v*`. Docker Hub publishing needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.
