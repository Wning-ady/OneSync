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
> OneSync 管理页使用独立管理口令登录，默认只将 `8098` 绑定到 Unraid 的 LAN 地址，并拒绝 Tailscale 非 LAN 来源。不要把端口转发到公网；未来确需通过反向代理访问时，必须配置来源限制、TLS，并把代理域名加入 `ONESYNC_ALLOWED_HOSTS`。

## 功能亮点

| 能力 | 说明 |
| --- | --- |
| 目录树选择 | 只同步勾选的 OneDrive 文件夹，范围清晰可控。 |
| 双设备代码授权 | OneDrive 同步引擎与 Microsoft Graph 分别授权，令牌隔离保存。 |
| 受控重同步 | 修改同步范围前先执行 dry-run，确认后才进行 resync；空范围直接拒绝。 |
| Graph 状态校验 | 定期验证 Microsoft Graph，分别显示授权中、待验证与连接异常。 |
| 安全默认值 | 不使用强制覆盖或 `--cleanup-local-files`，冲突由官方客户端保留副本。 |
| 单次同步 | 默认不运行持续监控，避免 Unraid 长期扫描；需要时手动同步一次。 |

## 快速部署

在 Unraid Compose Manager 中新建项目。先在项目目录创建 `.env`，随机管理口令必须至少 16 个字符：

```dotenv
ONESYNC_BIND_ADDRESS=192.168.2.21
ONESYNC_ADMIN_TOKEN=使用-openssl-rand-hex-24-生成的随机值
ONESYNC_ALLOWED_HOSTS=192.168.2.21,127.0.0.1,localhost
```

可以运行 `openssl rand -hex 24` 生成口令。不要把 `.env`、口令或 `docker compose config` 的输出提交到 Git。然后使用下面的配置，并将 `GRAPH_CLIENT_ID` 与 `GRAPH_TENANT_ID` 替换为自己的 Entra 应用信息。

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
      GRAPH_TENANT_ID: replace-with-your-tenant-id-or-domain
      ONESYNC_ADMIN_TOKEN: ${ONESYNC_ADMIN_TOKEN:?请在 .env 设置至少 16 字符的管理口令}
      ONESYNC_ALLOWED_HOSTS: ${ONESYNC_ALLOWED_HOSTS:-192.168.2.21,127.0.0.1,localhost}
    ports:
      - "${ONESYNC_BIND_ADDRESS:-192.168.2.21}:8098:8098"
    volumes:
      - /mnt/user/appdata/onesync:/onedrive/conf
      - /mnt/user/onedrive:/onedrive/data
    restart: unless-stopped
```

启动后打开 `http://192.168.2.21:8098`，输入 `.env` 中的 `ONESYNC_ADMIN_TOKEN`。登录会话保存在浏览器的 HttpOnly、SameSite Cookie 中；容器重启后需要重新登录。Compose Manager 用户需要确认 `PROJECTS_FOLDER` 与项目路径一致，并保留两个挂载：

- `/mnt/user/appdata/onesync:/onedrive/conf`：数据库、同步设置与 OAuth refresh token。
- `/mnt/user/onedrive:/onedrive/data`：OneDrive 真实文件副本。

使用仓库中的 `unraid/onesync.xml` 时，在 DockerMan 表单填写至少 16 字符的 `ONESYNC_ADMIN_TOKEN`。模板通过 `ExtraParams` 仅绑定 `192.168.2.21:8098`，因此不要再添加同名 Port 配置，否则会重新产生 `0.0.0.0:8098` 监听。若 Unraid 地址不同，请同时修改 XML 的 `ExtraParams`、`WebUI` 访问地址和 `ONESYNC_ALLOWED_HOSTS`。

建议在 Unraid 的 `DOCKER-USER` 防火墙链中只允许管理网段访问 TCP `8098`，并拒绝 WAN、Tailscale 非 LAN 来源和 IPv6。端口绑定限制目标地址，防火墙限制来源地址，两层应同时保留。

### 部署回滚

升级前备份 `/mnt/user/appdata/onesync`、`/mnt/user/onedrive` 和当前 XML/Compose 配置。Compose 回滚时将 `.env` 中的 `ONESYNC_IMAGE` 设为上一个确认可用的版本标签，再运行 `docker compose up -d`；不要删除两个持久化目录。Unraid XML 回滚时恢复备份模板或临时选择上一个版本镜像并重建容器，仍须保留管理口令、Host 白名单、LAN 端口绑定和防火墙规则。

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
| Graph 显示连接异常 | 点击“重新授权”完成设备代码流程；若只是网络中断，等待连接检查在网络恢复后自动重试。 |
| 设备代码无法复制 | 局域网 HTTP 受浏览器限制时，点击代码本身选中后按 `Ctrl+C`（Mac 按 `⌘+C`）。 |
| 管理页无法连接 | 检查 `ONESYNC_BIND_ADDRESS` 是否属于 Unraid、Host 是否在 `ONESYNC_ALLOWED_HOSTS`、端口 `8098`、防火墙和反向代理。 |
| 登录被拒绝 | 确认管理口令至少 16 字符且与容器环境变量一致；修改口令后重建容器并重新登录。 |
| 同步范围不正确 | 停止同步，确认页面范围与 `/onedrive/conf/sync_list` 一致，再执行受控重同步。 |
| 网络中断 | “同步一次”会报告错误并保持停止；网络恢复后再次运行。 |
| 本地文件看似消失 | 不要立即重同步或清理；先检查选定范围、客户端日志和 OneDrive 回收站。 |

## 镜像与发布

- Docker Hub：[`waning/onesync`](https://hub.docker.com/r/waning/onesync)
- GitHub Container Registry：`ghcr.io/wning-ady/onesync:latest`
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
