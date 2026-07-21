<p align="center">
  <img src="docs/assets/onesync-logo.png" width="160" alt="OneSync logo">
</p>

<h1 align="center">OneSync</h1>

<p align="center">Unraid 上可控、选择性同步 Microsoft OneDrive 的管理器。</p>

<p align="center">
  <a href="README.en.md">English</a> ·
  <a href="https://github.com/Wning-ady/OneSync/issues">问题反馈</a> ·
  <a href="https://hub.docker.com/r/waning/onesync">Docker Hub</a>
</p>

OneSync 使用维护活跃的 [`abraunegg/onedrive`](https://github.com/abraunegg/onedrive) 客户端同步真实本地文件，不使用 rclone FUSE 虚拟挂载。你可以在浏览器中选择 OneDrive 文件夹，文件会落盘到 Unraid；需要时手动执行一次同步即可上传本地改动、下载云端改动。

> [!IMPORTANT]
> OneSync 管理页默认监听 `8098`，不含内建账号系统。只在可信局域网、VPN 或已经配置认证的反向代理后访问，禁止直接暴露到公网。

## 功能亮点

| 能力 | 说明 |
| --- | --- |
| 目录树选择 | 只同步勾选的 OneDrive 文件夹，范围清晰可控。 |
| 双设备代码授权 | OneDrive 同步引擎与 Microsoft Graph 分别授权，令牌隔离保存。 |
| 受控重同步 | 修改同步范围前先执行 dry-run，确认后才进行 resync；空范围直接拒绝。 |
| 安全默认值 | 不使用强制覆盖或 `--cleanup-local-files`，冲突由官方客户端保留副本。 |
| 单次同步 | 默认不运行持续监控，避免 Unraid 长期扫描；需要时手动同步一次。 |

## 快速部署

在 Unraid Compose Manager 中新建项目，使用下面的配置，并将 `GRAPH_CLIENT_ID` 与 `GRAPH_TENANT_ID` 替换为你自己的 Entra 应用信息。

```yaml
services:
  onesync:
    image: docker.io/waning/onesync:latest
    container_name: onesync
    environment:
      PUID: "99"
      PGID: "100"
      TZ: Asia/Shanghai
      GRAPH_CLIENT_ID: replace-with-your-entra-client-id
      GRAPH_TENANT_ID: replace-with-your-tenant-id-or-domain
    ports:
      - "8098:8098"
    volumes:
      - /mnt/user/appdata/onesync:/onedrive/conf
      - /mnt/user/onedrive:/onedrive/data
    restart: unless-stopped
```

启动后打开 `http://<unraid-ip>:8098`。Compose Manager 用户需要确认 `PROJECTS_FOLDER` 与项目路径一致，并保留两个挂载：

- `/mnt/user/appdata/onesync:/onedrive/conf`：数据库、同步设置与 OAuth refresh token。
- `/mnt/user/onedrive:/onedrive/data`：OneDrive 真实文件副本。

## Entra 应用注册

1. 登录 [Microsoft Entra 管理中心](https://entra.microsoft.com/)，创建**单租户**应用注册。
2. 在“身份验证”中启用“允许公共客户端流”，添加以下重定向 URI：
   - `http://127.0.0.1:53100/`
   - `https://login.microsoftonline.com/common/oauth2/nativeclient`
3. 在“API 权限”添加委托权限：`Files.ReadWrite.All`、`User.Read`、`offline_access`。
4. 由租户管理员授予管理员同意，将“应用程序（客户端）ID”填写到 `GRAPH_CLIENT_ID`。

不需要、也不要填写 Client Secret。OneSync 使用设备代码流程完成授权。

## 首次授权与同步

1. 打开 OneSync，点击“同步一次”，按日志显示的设备代码在 Microsoft 页面登录目标工作账号。
2. 点击“连接 Graph”，完成第二个设备代码授权；Graph 只用于浏览目录树。
3. 点击“刷新目录”，勾选要保留在 Unraid 的文件夹并保存。
4. 点击“受控重同步”。只有 dry-run 成功后才会执行 resync；结束后同步进程保持停止。
5. 后续本地或云端有改动时，点击“同步一次”。

当前选择会写入 `/onedrive/conf/sync_list`。OneDrive 客户端启动时会校验该清单；健康接口会显示 `scopeConfigured: true`。

## 数据、安全与恢复

- `/mnt/user/onedrive` 保存选中目录的真实本地副本，建议纳入 Unraid 备份。
- `/mnt/user/appdata/onesync` 保存同步数据库、设置和 OAuth refresh token，必须备份且不得公开。
- 若数据目录可能在阵列未挂载时出现空目录，请在其根目录创建 `.nosync`；客户端已启用 `check_nomount=true`。
- 需要重新授权时，点击“同步授权”或“连接 Graph”，不要删除整个配置目录。
- 需要重建同步状态时，先备份配置与数据，再从管理页运行“受控重同步”。
- 不要启用 `--cleanup-local-files`，除非你已经确认本地文件和同步范围均可删除。

## 排障

| 现象 | 处理 |
| --- | --- |
| Graph 设备代码被拒绝 | 核对单租户设置、`GRAPH_CLIENT_ID`、`GRAPH_TENANT_ID` 和管理员同意的委托权限。 |
| 管理页无法连接 | 检查容器状态、端口 `8098`、Unraid 防火墙和反向代理。 |
| 同步范围不正确 | 停止同步，确认页面范围与 `/onedrive/conf/sync_list` 一致，再执行受控重同步。 |
| 网络中断 | “同步一次”会报告错误并保持停止；网络恢复后再次运行。 |
| 本地文件看似消失 | 不要立即重同步或清理；先检查选定范围、客户端日志和 OneDrive 回收站。 |

## 镜像与发布

- Docker Hub：[`waning/onesync`](https://hub.docker.com/r/waning/onesync)
- GitHub Container Registry：`ghcr.io/Wning-ady/onesync:latest`
- GitHub 仓库：[Wning-ady/OneSync](https://github.com/Wning-ady/OneSync)

直接拉取 Docker Hub 镜像：

```bash
docker pull docker.io/waning/onesync:latest
```

推送 `main` 或 `v*` 标签会触发 GitHub Actions。Docker Hub 发布需要仓库 Actions Secrets：`DOCKERHUB_USERNAME`、`DOCKERHUB_TOKEN`；`vX.Y.Z` 标签会同时发布对应版本镜像。

## 开发

```bash
python3 -m pytest -q
docker compose build
docker compose up
```

## 许可

未指定许可证前，保留全部权利。
