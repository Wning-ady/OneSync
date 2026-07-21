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

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"

    @property
    def device_code_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/devicecode"

    def auth_status(self) -> dict[str, str]:
        if not self.client_id:
            return {"state": "not_configured"}
        if self.pending and time.time() < self.pending.expires_at:
            return {"state": "pending"}
        if self.token_path.exists():
            return {"state": "authorized"}
        return {"state": "error" if self.auth_error else "unauthorized", "message": self.auth_error or ""}

    async def begin_device_code(self) -> dict[str, object]:
        if not self.client_id:
            raise GraphError("GRAPH_CLIENT_ID has not been configured.")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.device_code_url, data={"client_id": self.client_id, "scope": SCOPES})
        if response.is_error:
            raise GraphError("Microsoft rejected the device-code request. Check the tenant and application registration.")
        data = response.json()
        self.pending = PendingDeviceCode(data["device_code"], time.time() + int(data["expires_in"]), int(data.get("interval", 5)))
        return {key: data[key] for key in ("user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval", "message") if key in data}

    async def poll_device_code(self) -> dict[str, str]:
        pending = self.pending
        if not pending or time.time() >= pending.expires_at:
            self.pending = None
            raise GraphError("No active device-code authorization. Start a new authorization request.")
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
                self.auth_error = error
                raise GraphError(f"Microsoft authorization failed: {error}.")
        self.pending = None
        raise GraphError("The Microsoft device code expired.")

    async def _access_token(self, refresh: bool = False) -> str:
        tokens = read_json(self.token_path, {})
        if not isinstance(tokens, dict) or "access_token" not in tokens:
            raise GraphError("Authorize Microsoft Graph before browsing folders.")
        expires_at = float(tokens.get("obtained_at", 0)) + int(tokens.get("expires_in", 0)) - 60
        if refresh or (expires_at and time.time() >= expires_at):
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                raise GraphError("Graph token expired. Reauthorize this manager.")
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(self.token_url, data={
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": SCOPES,
                })
            if response.is_error:
                raise GraphError("Graph token expired. Reauthorize this manager.")
            updated = response.json()
            updated["refresh_token"] = updated.get("refresh_token", refresh_token)
            updated["obtained_at"] = time.time()
            write_json_private(self.token_path, updated)
            tokens = updated
        return str(tokens["access_token"])

    async def _graph_get(self, url: str) -> dict[str, object]:
        parsed = urlparse(url)
        if parsed.netloc != "graph.microsoft.com":
            raise GraphError("Invalid pagination cursor.")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {await self._access_token()}"})
            if response.status_code == 401:
                response = await client.get(url, headers={"Authorization": f"Bearer {await self._access_token(refresh=True)}"})
        if response.status_code == 401:
            raise GraphError("Graph token expired. Reauthorize this manager.")
        if response.status_code == 403:
            raise GraphError("Graph permission was denied. Grant delegated permissions and admin consent.")
        if response.is_error:
            raise GraphError(f"Graph folder request failed ({response.status_code}).")
        return response.json()

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
