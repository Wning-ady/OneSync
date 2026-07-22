from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .storage import read_json, write_json_private


class NotificationError(ValueError):
    pass


class NotificationManager:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, object]:
        value = read_json(self.path, {})
        return value if isinstance(value, dict) else {}

    def public(self) -> dict[str, object]:
        value = self.load()
        endpoint = str(value.get("webhookUrl", ""))
        return {"enabled": bool(value.get("enabled")), "configured": bool(endpoint), "endpointHost": urlparse(endpoint).netloc, "events": value.get("events", {"syncError": True, "graphDisconnected": True})}

    def save(self, enabled: bool, webhook_url: str, events: dict[str, bool]) -> dict[str, object]:
        webhook_url = webhook_url.strip()
        parsed = urlparse(webhook_url) if webhook_url else None
        if enabled and (not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc):
            raise NotificationError("启用通知时需要填写有效的 HTTP/HTTPS Webhook 地址。")
        write_json_private(self.path, {"enabled": enabled, "webhookUrl": webhook_url, "events": {"syncError": bool(events.get("syncError", True)), "graphDisconnected": bool(events.get("graphDisconnected", True))}, "updatedAt": datetime.now(timezone.utc).isoformat()})
        return self.public()

    async def send(self, event: str, severity: str, message: str, details: dict[str, object] | None = None) -> None:
        value = self.load()
        endpoint = str(value.get("webhookUrl", ""))
        if not endpoint or not value.get("enabled"):
            return
        payload = {"title": "OneSync 通知", "event": event, "severity": severity, "time": datetime.now(timezone.utc).isoformat(), "message": message[:500], "source": "OneSync", "details": details or {}}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(endpoint, json=payload)
        except httpx.HTTPError as error:
            raise NotificationError("Webhook 无法连接，请检查地址与网络。") from error
        if response.is_error:
            raise NotificationError(f"Webhook 返回 HTTP {response.status_code}。")

    async def send_test(self) -> None:
        if not self.load().get("webhookUrl"):
            raise NotificationError("请先保存 Webhook 地址。")
        was_enabled = bool(self.load().get("enabled"))
        if not was_enabled:
            value = self.load(); value["enabled"] = True; write_json_private(self.path, value)
        try:
            await self.send("test", "info", "Webhook 已连接。后续同步错误或 Graph 掉线会通知此地址。")
        finally:
            if not was_enabled:
                value = self.load(); value["enabled"] = False; write_json_private(self.path, value)
