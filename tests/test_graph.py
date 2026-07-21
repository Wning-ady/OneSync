import json

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
