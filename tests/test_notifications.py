from __future__ import annotations

import json

import pytest

from app.notifications import NotificationError, NotificationManager


WECOM_URL = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?"
    "key=11111111-2222-3333-4444-555555555555"
)


class FakeResponse:
    def __init__(self, result: dict[str, object], status_code: int = 200) -> None:
        self._result = result
        self.status_code = status_code
        self.is_error = status_code >= 400

    def json(self) -> dict[str, object]:
        return self._result


class FakeClient:
    def __init__(self, response: FakeResponse, requests: list[tuple[str, dict[str, object]]]) -> None:
        self.response = response
        self.requests = requests

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, endpoint: str, json: dict[str, object]) -> FakeResponse:
        self.requests.append((endpoint, json))
        return self.response


def test_save_preserves_secret_and_returns_masked_preview(tmp_path) -> None:
    path = tmp_path / "notifications.json"
    manager = NotificationManager(path)

    public = manager.save(True, WECOM_URL, {"syncError": True})

    assert public["configured"] is True
    assert public["endpointHost"] == "qyapi.weixin.qq.com"
    assert public["endpointPreview"] == (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=11111111...5555"
    )
    assert WECOM_URL not in json.dumps(public)
    assert json.loads(path.read_text())["webhookUrl"] == WECOM_URL
    assert path.stat().st_mode & 0o777 == 0o600


def test_blank_url_keeps_existing_webhook(tmp_path) -> None:
    path = tmp_path / "notifications.json"
    manager = NotificationManager(path)
    manager.save(True, WECOM_URL, {"syncError": True})

    manager.save(False, "", {"graphDisconnected": True})

    saved = json.loads(path.read_text())
    assert saved["webhookUrl"] == WECOM_URL
    assert saved["enabled"] is False
    assert saved["events"] == {"syncError": True, "graphDisconnected": True}


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
        "https://qyapi.weixin.qq.com/not-a-webhook?key=abc",
    ],
)
def test_rejects_invalid_wecom_endpoint(tmp_path, endpoint: str) -> None:
    manager = NotificationManager(tmp_path / "notifications.json")

    with pytest.raises(NotificationError, match="仅允许使用"):
        manager.save(True, endpoint, {})


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/webhook",
        "https://127.0.0.1/cgi-bin/webhook/send?key=11111111-2222-3333-4444-555555555555",
        WECOM_URL + "&next=http://127.0.0.1",
        "https://user:password@qyapi.weixin.qq.com/cgi-bin/webhook/send?key=11111111-2222-3333-4444-555555555555",
    ],
)
def test_rejects_non_allowlisted_endpoint(tmp_path, endpoint: str) -> None:
    manager = NotificationManager(tmp_path / "notifications.json")

    with pytest.raises(NotificationError, match="仅允许使用"):
        manager.save(True, endpoint, {})


@pytest.mark.asyncio
async def test_wecom_test_message_uses_markdown_and_does_not_enable_notifications(
    tmp_path, monkeypatch
) -> None:
    manager = NotificationManager(tmp_path / "notifications.json")
    manager.save(False, WECOM_URL, {})
    requests: list[tuple[str, dict[str, object]]] = []
    fake_client = FakeClient(FakeResponse({"errcode": 0, "errmsg": "ok"}), requests)
    async def public_resolution(_: str) -> None:
        return None

    monkeypatch.setattr(manager, "_assert_public_resolution", public_resolution)
    monkeypatch.setattr("app.notifications.httpx.AsyncClient", lambda **_: fake_client)

    await manager.send_test()

    assert manager.load()["enabled"] is False
    assert requests[0][0] == WECOM_URL
    assert requests[0][1]["msgtype"] == "markdown"
    content = requests[0][1]["markdown"]["content"]
    assert "OneSync 通知" in content
    assert "测试通知" in content


@pytest.mark.asyncio
async def test_wecom_api_error_is_reported(tmp_path, monkeypatch) -> None:
    manager = NotificationManager(tmp_path / "notifications.json")
    manager.save(True, WECOM_URL, {})
    fake_client = FakeClient(
        FakeResponse({"errcode": 93000, "errmsg": "invalid webhook url"}), []
    )
    async def public_resolution(_: str) -> None:
        return None

    monkeypatch.setattr(manager, "_assert_public_resolution", public_resolution)
    monkeypatch.setattr("app.notifications.httpx.AsyncClient", lambda **_: fake_client)

    with pytest.raises(NotificationError, match="invalid webhook url"):
        await manager.send_test()


@pytest.mark.asyncio
async def test_rejects_private_dns_resolution(tmp_path, monkeypatch) -> None:
    manager = NotificationManager(tmp_path / "notifications.json")
    manager.save(True, WECOM_URL, {})
    monkeypatch.setattr(
        "app.notifications.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )

    with pytest.raises(NotificationError, match="私网、回环、链路本地或保留地址"):
        await manager.send_test()


@pytest.mark.asyncio
async def test_rejects_webhook_redirect(tmp_path, monkeypatch) -> None:
    manager = NotificationManager(tmp_path / "notifications.json")
    manager.save(True, WECOM_URL, {})
    fake_client = FakeClient(FakeResponse({}, status_code=302), [])

    async def public_resolution(_: str) -> None:
        return None

    monkeypatch.setattr(manager, "_assert_public_resolution", public_resolution)
    monkeypatch.setattr("app.notifications.httpx.AsyncClient", lambda **_: fake_client)

    with pytest.raises(NotificationError, match="不允许的重定向"):
        await manager.send_test()
