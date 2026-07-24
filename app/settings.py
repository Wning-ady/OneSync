from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    data_dir: Path
    graph_client_id: str
    graph_tenant_id: str
    admin_token: str = ""
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")
    cookie_secure: bool = False

    @classmethod
    def from_environment(cls) -> "Settings":
        configured_hosts = tuple(
            host.strip().lower()
            for host in os.getenv("ONESYNC_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        )
        allowed_hosts = tuple(
            dict.fromkeys(("localhost", "127.0.0.1", "::1", *configured_hosts))
        )
        return cls(
            config_dir=Path(os.getenv("APP_CONFIG_DIR", "/onedrive/conf")),
            data_dir=Path(os.getenv("ONEDRIVE_DATA_DIR", "/onedrive/data")),
            graph_client_id=os.getenv("GRAPH_CLIENT_ID", ""),
            graph_tenant_id=os.getenv("GRAPH_TENANT_ID", "5dldn8.onmicrosoft.com"),
            admin_token=os.getenv("ONESYNC_ADMIN_TOKEN", ""),
            allowed_hosts=allowed_hosts,
            cookie_secure=os.getenv("ONESYNC_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
        )
