<p align="center">
  <img src="docs/assets/onesync-logo.png" width="160" alt="OneSync logo">
</p>

# OneSync

> Unraid 上可控、选择性同步 Microsoft OneDrive 的管理器。

[English](README.en.md) | [问题反馈](../../issues)

OneSync 使用维护活跃的 [`abraunegg/onedrive`](https://github.com/abraunegg/onedrive)
客户端同步真实本地文件，不使用 rclone FUSE 虚拟挂载。通过浏览器选定 OneDrive 文件夹后，文件会落盘到 Unraid；需要时运行一次同步即可上传本地改动、下载云端改动。

## 特性

- 目录树选择：只同步勾选的 OneDrive 文件夹。
- 双设备代码授权：OneDrive 同步引擎与 Microsoft Graph 分别授权，令牌隔离保存。
- 受控重同步：修改范围后先 dry-run，确认后再 resync，空范围被拒绝。
- 安全默认值：不使用强制覆盖或 `--cleanup-local-files`；冲突由官方客户端保留副本。
- 单次同步优先：默认不运行持续监控，避免 Unraid 长期扫描；需要时手动同步一次。
- 局域网管理：管理页默认端口 `8098`，不含内建账号系统。

## 快速部署

在 Unraid Compose Manager 新建项目，使用以下配置。将 `GRAPH_CLIENT_ID` 替换为 Entra 应用客户端 ID。

```yaml
services:
  onesync:
    image: ghcr.io/Wning-ady/onesync:latest
    container_name: onesync
    environment:
      PUID: "99"
      PGID: "100"
      TZ: Asia/Shanghai
      GRAPH_CLIENT_ID: replace-with-your-entra-client-id
      GRAPH_TENANT_ID: 5dldn8.onmicrosoft.com
    ports:
      - "8098:8098"
    volumes:
      - /mnt/user/appdata/onesync:/onedrive/conf
      - /mnt/user/onedrive:/onedrive/data
    restart: unless-stopped
```

打开 `http://<unraid-ip>:8098`。管理页只应在可信局域网、VPN 或现有反向代理认证后访问，不能直接暴露到互联网。

## Entra 应用注册

1. 登录 [Microsoft Entra 管理中心](https://entra.microsoft.com/)，创建**单租户**应用注册。
2. 在“身份验证”启用“允许公共客户端流”。添加重定向 URI：
   - `http://127.0.0.1:53100/`
   - `https://login.microsoftonline.com/common/oauth2/nativeclient`
3. 在“API 权限”添加委托权限：`Files.ReadWrite.All`、`User.Read`、`offline_access`。
4. 由租户管理员授予管理员同意。复制“应用程序（客户端）ID”到 `GRAPH_CLIENT_ID`。

不需要、也不要填写 Client Secret。

## 首次授权与同步

1. 打开 OneSync，点击“同步一次”。日志会显示 OneDrive 官方客户端设备代码；在提示的 Microsoft 页面以目标工作账号登录。
2. 点击“连接 Graph”，在页面显示的第二个设备代码流程中完成授权。Graph 仅用于浏览目录树。
3. 点击“刷新目录”，勾选要保留在 Unraid 的文件夹，确认保存。
4. 点击“受控重同步”。dry-run 成功后才会执行 resync；结束后同步进程保持停止。
5. 后续本地或云端有改动时，点击“同步一次”。

当前选择会写入 `/onedrive/conf/sync_list`。OneDrive 客户端启动时会校验该清单；管理页健康接口会显示 `scopeConfigured: true`。

## 数据与恢复

- 数据目录：`/mnt/user/onedrive`。它保存选中目录的真实副本。
- 私有配置：`/mnt/user/appdata/onesync`。包含同步数据库和 OAuth refresh token，必须备份且不得公开。
- 阵列未挂载保护：若数据目录可能在未挂载时出现空目录，在其根目录创建 `.nosync`；客户端已启用 `check_nomount=true`。
- 需要重新授权：点击“同步授权”或“连接 Graph”，不要删除整个配置目录。
- 需要重建同步状态：先备份配置与数据，再从管理页运行“受控重同步”。

## 排障

| 现象 | 处理 |
| --- | --- |
| Graph 设备代码被拒绝 | 核对单租户设置、`GRAPH_CLIENT_ID` 和管理员同意的委托权限。 |
| 管理页无法连接 | 检查容器状态、端口 `8098`、Unraid 防火墙和反向代理。 |
| 同步范围不正确 | 停止同步，确认页面范围与 `/onedrive/conf/sync_list` 一致，再执行受控重同步。 |
| 网络中断 | 同步一次会报告错误且保持停止；网络恢复后再次运行。 |
| 本地文件看似消失 | 不要立即重同步或清理；先检查选定范围、客户端日志和 OneDrive 回收站。 |

## 镜像与发布

- GitHub Container Registry：`ghcr.io/Wning-ady/onesync:latest`
- Docker Hub：`docker.io/<DOCKERHUB_USERNAME>/onesync:latest`

推送 `main` 或 `v*` 标签会触发 GitHub Actions。Docker Hub 发布需要仓库 Actions secrets：
`DOCKERHUB_USERNAME`、`DOCKERHUB_TOKEN`。`vX.Y.Z` 标签会同时发布对应版本镜像。

## 开发

```sh
python3 -m pytest -q
docker compose build
docker compose up
```

## 许可

未指定许可证前，保留全部权利。
