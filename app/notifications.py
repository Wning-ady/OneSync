from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlparse

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
        return {
            "enabled": bool(value.get("enabled")),
            "configured": bool(endpoint),
            "endpointHost": urlparse(endpoint).netloc,
            "endpointPreview": self._mask_endpoint(endpoint),
            "events": value.get(
                "events",
                {"syncError": True, "graphDisconnected": True},
            ),
        }

    def save(self, enabled: bool, webhook_url: str, events: dict[str, bool]) -> dict[str, object]:
        webhook_url = webhook_url.strip()
        # The browser intentionally clears the secret input after saving. An empty
        # value therefore means "keep the configured endpoint", not "erase it".
        if not webhook_url:
            webhook_url = str(self.load().get("webhookUrl", "")).strip()
        parsed = urlparse(webhook_url) if webhook_url else None
        if enabled and (not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc):
            raise NotificationError("启用通知时需要填写有效的 HTTP/HTTPS Webhook 地址。")
        if webhook_url:
            self._validate_endpoint(webhook_url)
        write_json_private(self.path, {"enabled": enabled, "webhookUrl": webhook_url, "events": {"syncError": bool(events.get("syncError", True)), "graphDisconnected": bool(events.get("graphDisconnected", True))}, "updatedAt": datetime.now(timezone.utc).isoformat()})
        return self.public()

    async def send(
        self,
        event: str,
        severity: str,
        message: str,
        details: dict[str, object] | None = None,
        *,
        force: bool = False,
    ) -> None:
        value = self.load()
        endpoint = str(value.get("webhookUrl", ""))
        if not endpoint or (not value.get("enabled") and not force):
            return
        payload = self._payload(endpoint, event, severity, message, details or {})
        await self._assert_public_resolution(endpoint)
        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(endpoint, json=payload)
        except httpx.HTTPError as error:
            raise NotificationError("Webhook 无法连接，请检查地址与网络。") from error
        if 300 <= response.status_code < 400:
            raise NotificationError("Webhook 返回了不允许的重定向。")
        if response.is_error:
            raise NotificationError(f"Webhook 返回 HTTP {response.status_code}。")
        if self._is_wecom(endpoint):
            try:
                result = response.json()
            except ValueError as error:
                raise NotificationError("企业微信 Webhook 返回了无法识别的响应。") from error
            if not isinstance(result, dict) or result.get("errcode") != 0:
                reason = str(result.get("errmsg", "未知错误")) if isinstance(result, dict) else "未知错误"
                raise NotificationError(f"企业微信 Webhook 发送失败：{reason}。")

    async def send_test(self) -> None:
        if not self.load().get("webhookUrl"):
            raise NotificationError("请先保存 Webhook 地址。")
        await self.send(
            "test",
            "info",
            "Webhook 已连接。后续同步错误或 Graph 掉线会通知此地址。",
            force=True,
        )

    @staticmethod
    def _is_wecom(endpoint: str) -> bool:
        parsed = urlparse(endpoint)
        return parsed.hostname == "qyapi.weixin.qq.com" and parsed.path == "/cgi-bin/webhook/send"

    @classmethod
    def _validate_endpoint(cls, endpoint: str) -> None:
        parsed = urlparse(endpoint)
        try:
            port = parsed.port
        except ValueError as error:
            raise NotificationError("企业微信机器人地址端口无效。") from error
        query = parse_qsl(parsed.query, keep_blank_values=True)
        key = query[0][1].strip() if len(query) == 1 and query[0][0] == "key" else ""
        valid_key = bool(
            re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                key,
            )
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname != "qyapi.weixin.qq.com"
            or parsed.path != "/cgi-bin/webhook/send"
            or parsed.params
            or parsed.fragment
            or parsed.username
            or parsed.password
            or port not in {None, 443}
            or not valid_key
        ):
            raise NotificationError(
                "仅允许使用包含有效 key 的 HTTPS 企业微信机器人 Webhook 地址。"
            )

    @classmethod
    async def _assert_public_resolution(cls, endpoint: str) -> None:
        cls._validate_endpoint(endpoint)
        hostname = urlparse(endpoint).hostname
        assert hostname
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                443,
                type=socket.SOCK_STREAM,
            )
        except OSError as error:
            raise NotificationError("企业微信 Webhook 域名无法解析。") from error
        addresses = {record[4][0] for record in records}
        if not addresses:
            raise NotificationError("企业微信 Webhook 域名没有可用地址。")
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as error:
                raise NotificationError("企业微信 Webhook 返回了无效地址。") from error
            if not address.is_global:
                raise NotificationError(
                    "企业微信 Webhook 解析到了私网、回环、链路本地或保留地址，已拒绝发送。"
                )

    @staticmethod
    def _mask_endpoint(endpoint: str) -> str:
        if not endpoint:
            return ""
        parsed = urlparse(endpoint)
        if parsed.hostname == "qyapi.weixin.qq.com":
            key = parse_qs(parsed.query).get("key", [""])[0]
            if key:
                masked_key = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "****"
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?key={masked_key}"
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    @classmethod
    def _payload(
        cls,
        endpoint: str,
        event: str,
        severity: str,
        message: str,
        details: dict[str, object],
    ) -> dict[str, object]:
        occurred_at = datetime.now(timezone.utc).isoformat()
        if cls._is_wecom(endpoint):
            event_name = {
                "test": "测试通知",
                "sync_error": "同步异常",
                "graph_disconnected": "Graph 连接断开",
            }.get(event, event)
            severity_name = {
                "info": "信息",
                "warning": "警告",
                "error": "错误",
            }.get(severity, severity)
            content = [
                "## OneSync 通知",
                f"> 事件：{event_name}",
                f"> 级别：{severity_name}",
                f"> 时间：{occurred_at}",
                "",
                str(message)[:500],
            ]
            path = str(details.get("path", "")).strip()
            action = str(details.get("action", "")).strip()
            if path:
                content.append(f"\n文件：{path[:500]}")
            if action:
                content.append(f"\n操作：{action[:200]}")
            return {"msgtype": "markdown", "markdown": {"content": "\n".join(content)}}
        return {
            "title": "OneSync 通知",
            "event": event,
            "severity": severity,
            "time": occurred_at,
            "message": str(message)[:500],
            "source": "OneSync",
            "details": details,
        }
