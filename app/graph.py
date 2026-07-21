from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from .storage import read_json, write_json_private

SCOPES = "offline_access User.Read Files.ReadWrite.All"


class GraphError(RuntimeError):
    pass


@dataclass
class PendingDeviceCode:
    device_code: str
    expires_at: float
    interval: int


class GraphClient:
    def __init__(self, client_id: str, tenant: str, token_path: Path) -> None:
        self.client_id = client_id
        self.tenant = tenant
        self.token_path = token_path
        self.pending: PendingDeviceCode | None = None
        self.folder_cache: dict[str, str] = {}
        self.cursors: dict[str, str] = {}
        self.auth_error: str | None = None
        self.last_verified_at: float | None = None
        self.last_checked_at: float | None = None
        self._check_lock = asyncio.Lock()
        self._poll_lock = asyncio.Lock()

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"

    @property
    def device_code_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/devicecode"

    def _mark_error(self, message: str) -> None:
        self.auth_error = message
        self.last_verified_at = None

    def auth_status(self) -> dict[str, object]:
        if not self.client_id:
            return {"state": "not_configured", "message": "GRAPH_CLIENT_ID 尚未配置", "verified": False}
        if self.pending:
            if time.time() < self.pending.expires_at:
                return {"state": "pending", "message": "请在 Microsoft 页面完成设备代码授权", "verified": False}
            self.pending = None
            self._mark_error("设备代码已过期，请重新发起授权。")
        tokens = read_json(self.token_path, {})
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            message = self.auth_error or "尚未完成 Microsoft Graph 授权。"
            return {"state": "error" if self.auth_error else "unauthorized", "message": message, "verified": False}
        if self.auth_error:
            return {"state": "error", "message": self.auth_error, "verified": False}
        return {
            "state": "authorized",
            "message": "",
            "verified": self.last_verified_at is not None,
            "lastVerifiedAt": self.last_verified_at,
        }

    async def begin_device_code(self) -> dict[str, object]:
        if not self.client_id:
            raise GraphError("GRAPH_CLIENT_ID has not been configured.")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(self.device_code_url, data={"client_id": self.client_id, "scope": SCOPES})
        except httpx.HTTPError as error:
            self._mark_error("无法连接 Microsoft 授权服务，请检查网络后重试。")
            raise GraphError(self.auth_error) from error
        if response.is_error:
            self._mark_error("Microsoft 拒绝了设备代码请求，请检查租户和应用注册。")
            raise GraphError(self.auth_error)
        data = response.json()
        self.pending = PendingDeviceCode(data["device_code"], time.time() + int(data["expires_in"]), int(data.get("interval", 5)))
        self.auth_error = None
        self.last_verified_at = None
        self.last_checked_at = None
        return {key: data[key] for key in ("user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval", "message") if key in data}

    async def poll_device_code(self) -> dict[str, str]:
        async with self._poll_lock:
            pending = self.pending
            if not pending:
                if self.auth_status()["state"] == "authorized":
                    return {"state": "authorized"}
                message = self.auth_error or "没有正在进行的设备代码授权，请重新发起授权。"
                raise GraphError(message)
            if time.time() >= pending.expires_at:
                self.pending = None
                self._mark_error("设备代码已过期，请重新发起授权。")
                raise GraphError(self.auth_error)
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    while time.time() < pending.expires_at:
                        response = await client.post(self.token_url, data={
                            "client_id": self.client_id,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                            "device_code": pending.device_code,
                        })
                        if response.is_success:
                            tokens = response.json()
                            tokens["obtained_at"] = time.time()
                            write_json_private(self.token_path, tokens)
                            self.pending = None
                            self.auth_error = None
                            self.last_verified_at = None
                            self.last_checked_at = None
                            return {"state": "authorized"}
                        error = response.json().get("error", "authorization_pending")
                        if error == "authorization_pending":
                            await asyncio.sleep(pending.interval)
                            continue
                        if error == "slow_down":
                            pending.interval += 5
                            await asyncio.sleep(pending.interval)
                            continue
                        self.pending = None
                        message = {
                            "authorization_declined": "Microsoft 拒绝了授权，请重新发起授权。",
                            "expired_token": "设备代码已过期，请重新发起授权。",
                            "invalid_grant": "授权无效，请确认使用了同一租户账号。",
                        }.get(error, f"Microsoft 授权失败：{error}。")
                        self._mark_error(message)
                        raise GraphError(message)
            except httpx.HTTPError as error:
                self._mark_error("无法连接 Microsoft 授权服务，请检查网络后重试。")
                raise GraphError(self.auth_error) from error
            self.pending = None
            self._mark_error("设备代码已过期，请重新发起授权。")
            raise GraphError(self.auth_error)

    async def _access_token(self, refresh: bool = False) -> str:
        tokens = read_json(self.token_path, {})
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            message = "请先完成 Microsoft Graph 授权，再浏览文件夹。"
            self._mark_error(message)
            raise GraphError(message)
        try:
            expires_at = float(tokens.get("obtained_at", 0)) + int(tokens.get("expires_in", 0)) - 60
        except (TypeError, ValueError):
            message = "Graph 授权文件无效，请重新连接 Graph。"
            self._mark_error(message)
            raise GraphError(message)
        if refresh or (expires_at and time.time() >= expires_at):
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                message = "Graph 授权已过期，请重新连接 Graph。"
                self._mark_error(message)
                raise GraphError(message)
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(self.token_url, data={
                        "client_id": self.client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "scope": SCOPES,
                    })
            except httpx.HTTPError as error:
                message = "无法连接 Microsoft 授权服务，请检查网络后重试。"
                self._mark_error(message)
                raise GraphError(message) from error
            if response.is_error:
                message = "Graph 授权已过期，请重新连接 Graph。"
                self._mark_error(message)
                raise GraphError(message)
            updated = response.json()
            updated["refresh_token"] = updated.get("refresh_token", refresh_token)
            updated["obtained_at"] = time.time()
            write_json_private(self.token_path, updated)
            tokens = updated
            self.auth_error = None
        return str(tokens["access_token"])

    async def _graph_get(self, url: str) -> dict[str, object]:
        parsed = urlparse(url)
        if parsed.netloc != "graph.microsoft.com":
            raise GraphError("Invalid pagination cursor.")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {await self._access_token()}"})
                if response.status_code == 401:
                    response = await client.get(url, headers={"Authorization": f"Bearer {await self._access_token(refresh=True)}"})
        except httpx.HTTPError as error:
            message = "无法连接 Microsoft Graph，请检查网络后重试。"
            self._mark_error(message)
            raise GraphError(message) from error
        if response.status_code == 401:
            message = "Graph 授权已过期，请重新连接 Graph。"
            self._mark_error(message)
            raise GraphError(message)
        if response.status_code == 403:
            message = "Graph 权限被拒绝，请授予 Files.ReadWrite.All 管理员同意。"
            self._mark_error(message)
            raise GraphError(message)
        if response.is_error:
            message = f"Graph 请求失败（HTTP {response.status_code}），请稍后重试。"
            self._mark_error(message)
            raise GraphError(message)
        self.auth_error = None
        self.last_verified_at = time.time()
        self.last_checked_at = self.last_verified_at
        return response.json()

    async def check_connection(self, force: bool = False) -> dict[str, object]:
        """Verify a saved token at a bounded rate so health never lies about connectivity."""
        status = self.auth_status()
        if status["state"] not in {"authorized", "error"}:
            return status
        tokens = read_json(self.token_path, {})
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            return status
        if not force and self.last_checked_at and time.time() - self.last_checked_at < 30:
            return status
        async with self._check_lock:
            status = self.auth_status()
            if status["state"] not in {"authorized", "error"}:
                return status
            tokens = read_json(self.token_path, {})
            if not isinstance(tokens, dict) or not tokens.get("access_token"):
                return status
            self.last_checked_at = time.time()
            try:
                await asyncio.wait_for(
                    self._graph_get("https://graph.microsoft.com/v1.0/me/drive?$select=id"),
                    timeout=8,
                )
            except asyncio.TimeoutError:
                self._mark_error("Microsoft Graph 响应超时，请检查网络后重试。")
            except GraphError:
                pass
            return self.auth_status()

    async def folders(self, parent_id: str = "root", cursor: str | None = None) -> dict[str, object]:
        if cursor:
            url = self.cursors.pop(cursor, None)
            if not url:
                raise GraphError("Folder page expired; reload the folder.")
        elif parent_id == "root":
            url = "https://graph.microsoft.com/v1.0/me/drive/root/children?$select=id,name,folder&$top=200"
        else:
            if parent_id not in self.folder_cache:
                raise GraphError("Unknown folder. Reload the folder tree.")
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{parent_id}/children?$select=id,name,folder&$top=200"
        data = await self._graph_get(url)
        parent_path = "" if parent_id == "root" else self.folder_cache[parent_id]
        items: list[dict[str, str]] = []
        for entry in data.get("value", []):
            if "folder" not in entry or any(ch in str(entry.get("name", "")) for ch in "\r\n\\"):
                continue
            path = "/".join(value for value in (parent_path, str(entry["name"])) if value)
            self.folder_cache[str(entry["id"])] = path
            items.append({"id": str(entry["id"]), "name": str(entry["name"]), "path": path})
        next_link = data.get("@odata.nextLink")
        next_cursor = None
        if isinstance(next_link, str):
            next_cursor = uuid4().hex
            self.cursors[next_cursor] = next_link
        return {"items": items, "nextCursor": next_cursor}
