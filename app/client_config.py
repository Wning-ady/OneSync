from __future__ import annotations

import re

from .selection import SelectionStore
from .settings import Settings


def ensure_client_config(settings: Settings) -> None:
    """Create config and remove a legacy unsupported scope option safely."""
    config = settings.config_dir / "config"
    if config.exists():
        content = config.read_text(encoding="utf-8")
    else:
        application_id = settings.graph_client_id or ""
        content = (
            "azure_tenant_id = \"%s\"\napplication_id = \"%s\"\nuse_device_auth = \"true\"\n"
            "check_nomount = \"true\"\nbypass_data_preservation = \"false\"\nuse_recycle_bin = \"true\"\n"
            % (settings.graph_tenant_id, application_id)
        )

    # driveone/onedrive discovers a file named `sync_list` inside --confdir.
    # It does not support a `sync_list = ...` config key. Remove the key written by
    # an earlier manager build; leaving it makes every client command fail validation.
    pattern = r"(?m)^\s*sync_list\s*=.*(?:\n|$)"
    content = re.sub(pattern, "", content)
    for option in ('force_http_11 = "true"', 'ip_protocol_version = "1"', 'display_transfer_metrics = "true"'):
        key = option.split(" =", 1)[0]
        if not re.search(rf"(?m)^\s*{re.escape(key)}\s*=", content):
            if content and not content.endswith("\n"):
                content += "\n"
            content += option + "\n"
    config.write_text(content, encoding="utf-8")
    config.chmod(0o600)


def scope_is_configured(settings: Settings, selection: SelectionStore) -> bool:
    config = settings.config_dir / "config"
    if not config.is_file() or not selection.path.is_file() or not selection.load():
        return False
    return not bool(re.search(r"(?m)^\s*sync_list\s*=", config.read_text(encoding="utf-8")))
