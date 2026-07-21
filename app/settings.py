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

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            config_dir=Path(os.getenv("APP_CONFIG_DIR", "/onedrive/conf")),
            data_dir=Path(os.getenv("ONEDRIVE_DATA_DIR", "/onedrive/data")),
            graph_client_id=os.getenv("GRAPH_CLIENT_ID", ""),
            graph_tenant_id=os.getenv("GRAPH_TENANT_ID", "5dldn8.onmicrosoft.com"),
        )
