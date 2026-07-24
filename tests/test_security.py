from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


ADMIN_TOKEN = "correct-horse-battery-staple"
BASE_URL = "http://192.168.2.21"


def client_for(tmp_path, token: str = ADMIN_TOKEN) -> TestClient:
    settings = Settings(
        tmp_path / "config",
        tmp_path / "data",
        "",
        "tenant.example",
        token,
        ("localhost", "127.0.0.1", "::1", "192.168.2.21"),
    )
    return TestClient(create_app(settings), base_url=BASE_URL)


def login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"token": ADMIN_TOKEN},
        headers={"Origin": BASE_URL},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    return response.json()["csrfToken"]


def test_api_requires_authentication_but_health_is_minimal(tmp_path) -> None:
    with client_for(tmp_path) as client:
        protected = [
            ("GET", "/api/logs"),
            ("GET", "/api/notifications"),
            ("PUT", "/api/notifications"),
            ("POST", "/api/notifications/test"),
            ("GET", "/api/selection"),
            ("POST", "/api/selection/preview"),
            ("POST", "/api/selection/apply"),
            ("POST", "/api/sync/start"),
            ("POST", "/api/sync/once"),
            ("POST", "/api/sync/stop"),
            ("POST", "/api/sync/reauth"),
            ("POST", "/api/sync/resync"),
            ("GET", "/api/graph/auth/status"),
            ("GET", "/api/graph/status"),
            ("GET", "/api/graph/auth/check"),
            ("POST", "/api/graph/auth/device-code"),
            ("POST", "/api/graph/auth/poll"),
            ("GET", "/api/folders"),
        ]
        for method, path in protected:
            assert client.request(method, path).status_code == 401
        health = client.get("/api/health")
        assert health.status_code == 200
        assert set(health.json()) == {"ok", "version"}
        assert health.headers["Cache-Control"] == "no-store"
        assert health.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in health.headers["Content-Security-Policy"]
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_login_session_and_csrf_protect_control_routes(tmp_path) -> None:
    with client_for(tmp_path) as client:
        csrf = login(client)
        assert client.get("/api/logs").status_code == 200
        assert client.get("/api/auth/session").json()["authenticated"] is True
        assert "sync" in client.get("/api/health").json()
        assert client.post("/api/sync/stop", headers={"Origin": BASE_URL}).status_code == 403
        response = client.post(
            "/api/sync/stop",
            headers={"Origin": BASE_URL, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        logout = client.post(
            "/api/auth/logout",
            headers={"Origin": BASE_URL, "X-CSRF-Token": csrf},
        )
        assert logout.status_code == 200
        assert client.get("/api/logs").status_code == 401


def test_rejects_untrusted_host_and_cross_site_origin(tmp_path) -> None:
    with client_for(tmp_path) as client:
        bad_host = client.get("/api/health", headers={"Host": "attacker.example"})
        assert bad_host.status_code == 400
        other_private_host = client.get("/api/health", headers={"Host": "192.168.2.99"})
        assert other_private_host.status_code == 400
        bad_origin = client.post(
            "/api/auth/login",
            json={"token": ADMIN_TOKEN},
            headers={"Origin": "https://attacker.example"},
        )
        assert bad_origin.status_code == 403
        cross_site = client.post(
            "/api/auth/login",
            json={"token": ADMIN_TOKEN},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert cross_site.status_code == 403


def test_login_is_rate_limited(tmp_path) -> None:
    with client_for(tmp_path) as client:
        for _ in range(5):
            assert client.post(
                "/api/auth/login",
                json={"token": "incorrect-token-value"},
                headers={"Origin": BASE_URL},
            ).status_code == 401
        response = client.post(
            "/api/auth/login",
            json={"token": "incorrect-token-value"},
            headers={"Origin": BASE_URL},
        )
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0


def test_short_or_missing_admin_token_fails_closed(tmp_path) -> None:
    with client_for(tmp_path, token="short") as client:
        session = client.get("/api/auth/session").json()
        assert session == {"authenticated": False, "configured": False}
        response = client.post(
            "/api/auth/login",
            json={"token": "short"},
            headers={"Origin": BASE_URL},
        )
        assert response.status_code == 503


def test_environment_allowed_hosts_are_explicit(monkeypatch) -> None:
    monkeypatch.setenv("ONESYNC_ALLOWED_HOSTS", "192.168.2.21,unraid.example")
    settings = Settings.from_environment()

    assert settings.allowed_hosts == (
        "localhost",
        "127.0.0.1",
        "::1",
        "192.168.2.21",
        "unraid.example",
    )
