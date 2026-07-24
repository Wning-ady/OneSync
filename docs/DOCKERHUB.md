<p align="center">
  <img src="https://raw.githubusercontent.com/Wning-ady/OneSync/main/docs/assets/onesync-logo.png" width="140" alt="OneSync logo">
</p>

# OneSync

OneSync 是面向 Unraid 的 OneDrive 双向同步管理容器，基于维护活跃的 `abraunegg/onedrive`。它提供浏览器管理页、设备代码授权、文件夹范围选择、单次同步、持续同步、受控重同步、中文日志和企业微信通知。

## v0.1.4 安全更新

- 新增管理口令登录、HttpOnly/SameSite 会话与 CSRF 防护
- 增加严格 Host/Origin 校验、跨站请求防护和 API 速率限制
- 管理端口仅绑定指定 Unraid LAN 地址
- Webhook 仅允许 HTTPS 企业微信机器人，并拒绝私网 DNS、环境代理与重定向
- 固定基础镜像摘要，使用带哈希的 Python 依赖锁定文件
- 构建阶段自动运行测试，生产镜像移除 pip、setuptools 和 wheel
- 发布流水线加入 Gitleaks、Hadolint、Trivy、Semgrep、SBOM、provenance 与 Cosign 签名

## 快速部署

镜像：`docker.io/waning/onesync:latest` 或 `docker.io/waning/onesync:0.1.4`

必填配置：

- `GRAPH_CLIENT_ID`：Entra 应用 Client ID
- `GRAPH_TENANT_ID`：租户 ID 或域名
- `ONESYNC_ADMIN_TOKEN`：至少 16 字符的随机管理口令
- `ONESYNC_ALLOWED_HOSTS`：允许访问的 Unraid IP 或域名

持久化目录：

- `/onedrive/conf`：授权、数据库和私有配置
- `/onedrive/data`：真实同步文件

默认管理端口为 `8098`。只应绑定可信 LAN/VPN 地址，禁止直接暴露公网。升级前请备份两个持久化目录和部署配置。

完整 Compose、Unraid XML、Entra 权限、升级和回滚说明：
[github.com/Wning-ady/OneSync](https://github.com/Wning-ady/OneSync)

---

OneSync is a bidirectional OneDrive sync manager for Unraid, built on the maintained `abraunegg/onedrive` client. It provides a browser UI, device-code authorization, selective folder sync, one-shot and continuous sync, controlled resync, logs, and WeCom notifications.

## v0.1.4 Security Update

- Admin-token login with HttpOnly/SameSite sessions and CSRF protection
- Strict Host/Origin validation, cross-site request protection, and API rate limiting
- Management port binding to an explicit Unraid LAN address
- HTTPS-only WeCom webhook allowlist with private-DNS, proxy, and redirect rejection
- Digest-pinned base image and hash-locked Python dependencies
- Build-time tests and removal of pip, setuptools, and wheel from the production image
- CI security gates plus SBOM, provenance, and keyless Cosign signing

## Quick Deployment

Image: `docker.io/waning/onesync:latest` or `docker.io/waning/onesync:0.1.4`

Required settings:

- `GRAPH_CLIENT_ID`: Entra application client ID
- `GRAPH_TENANT_ID`: tenant ID or domain
- `ONESYNC_ADMIN_TOKEN`: random admin token with at least 16 characters
- `ONESYNC_ALLOWED_HOSTS`: allowed Unraid IP addresses or hostnames

Persistent paths:

- `/onedrive/conf`: authorization, database, and private configuration
- `/onedrive/data`: synchronized files

The management service uses port `8098`. Bind it only to a trusted LAN or VPN address and never expose it directly to the internet. Back up both persistent paths and the deployment configuration before upgrading.

Full deployment and recovery documentation:
[github.com/Wning-ady/OneSync](https://github.com/Wning-ady/OneSync)
