from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


BASE_URL = "http://192.168.2.21"


def client_for(tmp_path) -> TestClient:
    settings = Settings(
        tmp_path / "config",
        tmp_path / "data",
        "",
        "tenant.example",
        ("localhost", "127.0.0.1", "::1", "192.168.2.21"),
    )
    return TestClient(create_app(settings), base_url=BASE_URL)


def test_api_is_available_without_a_login(tmp_path) -> None:
    with client_for(tmp_path) as client:
        assert client.get("/api/logs").status_code == 200
        assert client.get("/api/selection").status_code == 200
        health = client.get("/api/health")
        assert health.status_code == 200
        assert "sync" in health.json()
        assert health.headers["Cache-Control"] == "no-store"
        assert health.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in health.headers["Content-Security-Policy"]
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_rejects_untrusted_host_and_cross_site_control_request(tmp_path) -> None:
    with client_for(tmp_path) as client:
        bad_host = client.get("/api/health", headers={"Host": "attacker.example"})
        assert bad_host.status_code == 400
        cross_site = client.post(
            "/api/sync/stop",
            headers={"Origin": "https://attacker.example"},
        )
        assert cross_site.status_code == 403
        same_site = client.post("/api/sync/stop", headers={"Origin": BASE_URL})
        assert same_site.status_code == 200


def test_control_routes_are_rate_limited(tmp_path) -> None:
    with client_for(tmp_path) as client:
        for _ in range(30):
            assert client.post("/api/sync/stop", headers={"Origin": BASE_URL}).status_code == 200
        response = client.post("/api/sync/stop", headers={"Origin": BASE_URL})
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0


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
