<p align="center">
  <img src="https://raw.githubusercontent.com/Wning-ady/OneSync/main/docs/assets/onesync-logo.png" width="140" alt="OneSync logo">
</p>

# OneSync

OneSync 是面向 Unraid 的 OneDrive 双向同步管理容器，基于维护活跃的 `abraunegg/onedrive`。它提供浏览器管理页、设备代码授权、文件夹范围选择、单次同步、持续同步、受控重同步、中文日志和企业微信通知。

## v0.1.11 空闲传输状态修复

- 空闲时不再把未提供的待下载数量显示为 `null`

## v0.1.10 HTTP 授权码复制修复

- 为非 HTTPS 的 Unraid 管理页增加浏览器兼容复制回退和清晰结果提示

## v0.1.9 构建热修复

- 修复 React 前端构建阶段的基础镜像参数作用域，恢复发布流水线

## v0.1.8 React 前端与免口令访问

- 管理页改为 React + TypeScript + 原生 CSS，保留同步、授权、范围、通知、日志与关于页功能
- 移除内置管理口令与浏览器会话，LAN 内直接访问管理页
- 容器将两个挂载根目录设置为 `drwxrwxrwx`，便于 Unraid、SMB 与同步进程协作

## v0.1.7 Graph 状态热修复

- 恢复独立的 Graph 连通性校验，保持管理页健康状态轻量且不阻塞

## v0.1.6 交互与重同步可见性更新

- 深色紧凑管理界面，统一同步、通知、关于页面的视觉层级
- 健康状态改为本地快速响应，避免慢速 Graph 请求阻塞管理页
- 日志仅读取最近记录并按传输、完成、警告、错误分色
- 重同步显示云端条目扫描数、待下载数和当前工作阶段
- HTTP 403 下载失败按单个文件归因，避免多个失败项混淆

## v0.1.5 同步稳定性修复

- 网络不稳定场景将 OneDrive 并发线程固定为 3，降低 Graph 连接被对端重置的概率
- 下载失败事件识别超过本地 255 字节上限的文件名，并提示在云端缩短名称
- 保留 HTTP/1.1、IPv4 和传输指标配置

## v0.1.4 安全更新

- 增加严格 Host/Origin 校验、跨站请求防护和 API 速率限制
- 管理端口仅绑定指定 Unraid LAN 地址
- Webhook 仅允许 HTTPS 企业微信机器人，并拒绝私网 DNS、环境代理与重定向
- 固定基础镜像摘要，使用带哈希的 Python 依赖锁定文件
- 构建阶段自动运行测试，生产镜像移除 pip、setuptools 和 wheel
- 发布流水线加入 Gitleaks、Hadolint、Trivy、Semgrep、SBOM、provenance 与 Cosign 签名

## 快速部署

镜像：`docker.io/waning/onesync:latest` 或 `docker.io/waning/onesync:0.1.11`

必填配置：

- `GRAPH_CLIENT_ID`：Entra 应用 Client ID
- `GRAPH_TENANT_ID`：租户 ID 或域名
- `ONESYNC_ALLOWED_HOSTS`：允许访问的 Unraid IP 或域名

持久化目录：

- `/onedrive/conf`：授权、数据库和私有配置
- `/onedrive/data`：真实同步文件

默认管理端口为 `8098`。只应绑定可信 LAN/VPN 地址，禁止直接暴露公网。升级前请备份两个持久化目录和部署配置。

完整 Compose、Unraid XML、Entra 权限、升级和回滚说明：
[github.com/Wning-ady/OneSync](https://github.com/Wning-ady/OneSync)

---

OneSync is a bidirectional OneDrive sync manager for Unraid, built on the maintained `abraunegg/onedrive` client. It provides a browser UI, device-code authorization, selective folder sync, one-shot and continuous sync, controlled resync, logs, and WeCom notifications.

## v0.1.11 Idle Transfer Status Fix

- Do not render an unavailable pending-download count as `null` while the engine is idle

## v0.1.10 HTTP Device-code Copy Fix

- Add a compatible clipboard fallback and visible result for non-HTTPS Unraid management pages

## v0.1.9 Build Hotfix

- Fix the React frontend-builder base-image argument scope and restore the release pipeline

## v0.1.8 React UI and Password-Free LAN Access

- React + TypeScript + native CSS management UI with sync, authorization, scope, notifications, logs, and about views
- Remove built-in admin-token sessions for direct trusted-LAN access
- Set both mounted root directories to `drwxrwxrwx` for Unraid, SMB, and sync-process collaboration

## v0.1.7 Graph Status Hotfix

- Restore independent Graph connectivity checks while keeping management health lightweight and non-blocking

## v0.1.6 Interaction and Resync Visibility

- Compact dark management interface with consistent sync, notifications, and about views
- Local fast health responses so slow Graph calls do not block the management page
- Recent log window with transfer, completion, warning, and error colors
- Resync visibility for scanned cloud items, planned downloads, and current work phase
- Per-file HTTP 403 classification to keep multiple failures distinct

## v0.1.5 Sync Stability Fix

- Fix OneDrive worker concurrency at 3 to reduce Graph peer resets on unstable links
- Detect local 255-byte filename limit failures and explain that the cloud name must be shortened
- Keep HTTP/1.1, IPv4, and transfer metrics enabled

## v0.1.4 Security Update

- Strict Host/Origin validation, cross-site request protection, and API rate limiting
- Management port binding to an explicit Unraid LAN address
- HTTPS-only WeCom webhook allowlist with private-DNS, proxy, and redirect rejection
- Digest-pinned base image and hash-locked Python dependencies
- Build-time tests and removal of pip, setuptools, and wheel from the production image
- CI security gates plus SBOM, provenance, and keyless Cosign signing

## Quick Deployment

Image: `docker.io/waning/onesync:latest` or `docker.io/waning/onesync:0.1.11`

Required settings:

- `GRAPH_CLIENT_ID`: Entra application client ID
- `GRAPH_TENANT_ID`: tenant ID or domain
- `ONESYNC_ALLOWED_HOSTS`: allowed Unraid IP addresses or hostnames

Persistent paths:

- `/onedrive/conf`: authorization, database, and private configuration
- `/onedrive/data`: synchronized files

The management service uses port `8098`. Bind it only to a trusted LAN or VPN address and never expose it directly to the internet. Back up both persistent paths and the deployment configuration before upgrading.

Full deployment and recovery documentation:
[github.com/Wning-ady/OneSync](https://github.com/Wning-ady/OneSync)
