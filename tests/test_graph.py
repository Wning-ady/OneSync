import json
import time

import httpx
import pytest

from app.graph import GraphClient, GraphError


@pytest.mark.asyncio
async def test_folder_cursor_is_server_side(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client = GraphClient("client", "tenant", tmp_path / "token.json")
    client.token_path.write_text(json.dumps({"access_token": "secret"}))

    async def fake_get(_: str):
        return {"value": [{"id": "a", "name": "Documents", "folder": {}}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"}

    monkeypatch.setattr(client, "_graph_get", fake_get)
    page = await client.folders()
    assert page["items"] == [{"id": "a", "name": "Documents", "path": "Documents"}]
    assert page["nextCursor"]
    with pytest.raises(GraphError):
        await client.folders(cursor="https://evil.example")


@pytest.mark.asyncio
async def test_device_code_does_not_return_device_secret(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client = GraphClient("client", "tenant", tmp_path / "token.json")

    class Response:
        is_error = False
        def json(self): return {"device_code": "private", "user_code": "ABCD", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 900}

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return Response()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: Session())
    result = await client.begin_device_code()
    assert result["user_code"] == "ABCD"
    assert "device_code" not in result


def test_auth_status_validates_token_shape(tmp_path) -> None:
    token_path = tmp_path / "token.json"
    client = GraphClient("client", "tenant", token_path)

    token_path.write_text("{}")
    assert client.auth_status()["state"] == "unauthorized"

    token_path.write_text(json.dumps({"access_token": "secret"}))
    status = client.auth_status()
    assert status["state"] == "authorized"
    assert status["verified"] is False

    client.auth_error = "Graph token expired."
    assert client.auth_status()["state"] == "error"


@pytest.mark.asyncio
async def test_poll_is_idempotent_after_another_request_authorized(tmp_path) -> None:
    client = GraphClient("client", "tenant", tmp_path / "token.json")
    client.token_path.write_text(json.dumps({"access_token": "secret"}))
    assert await client.poll_device_code() == {"state": "authorized"}


@pytest.mark.asyncio
async def test_graph_error_marks_connection_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client = GraphClient("client", "tenant", tmp_path / "token.json")
    client.token_path.write_text(json.dumps({"access_token": "secret"}))

    async def fake_token(refresh: bool = False) -> str:
        return "secret"

    class Response:
        status_code = 403
        is_error = True

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr(client, "_access_token", fake_token)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: Session())

    with pytest.raises(GraphError):
        await client._graph_get("https://graph.microsoft.com/v1.0/me/drive?$select=id")
    assert client.auth_status()["state"] == "error"


@pytest.mark.asyncio
async def test_connection_check_marks_token_verified(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client = GraphClient("client", "tenant", tmp_path / "token.json")
    client.token_path.write_text(json.dumps({"access_token": "secret"}))

    async def fake_get(_: str):
        client.last_verified_at = time.time()
        return {"id": "drive"}

    monkeypatch.setattr(client, "_graph_get", fake_get)
    status = await client.check_connection(force=True)
    assert status["state"] == "authorized"
    assert status["verified"] is True
