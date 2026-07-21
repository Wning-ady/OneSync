from pathlib import Path

import pytest

from app.client_config import ensure_client_config, scope_is_configured
from app.selection import SelectionStore, normalize_paths
from app.settings import Settings


def test_normalizes_descendants_and_writes_private_file(tmp_path: Path) -> None:
    store = SelectionStore(tmp_path / "sync_list")
    assert store.save(["Documents/Projects", "Documents", "Photos"]) == ["Documents", "Photos"]
    assert (tmp_path / "sync_list").read_text() == "Documents\nPhotos\n"
    assert (tmp_path / "sync_list").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("path", ["", "/Documents", "../Documents", "Documents\\bad", "Documents\nInjected"])
def test_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        normalize_paths([path])


def test_empty_selection_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SelectionStore(tmp_path / "sync_list").save([])


def test_client_config_removes_unsupported_legacy_scope_option(tmp_path: Path) -> None:
    settings = Settings(tmp_path, tmp_path / "data", "client-id", "tenant")
    settings.config_dir.mkdir(exist_ok=True)
    (settings.config_dir / "config").write_text('custom_option = "keep"\nsync_list = "old"\n')
    store = SelectionStore(settings.config_dir / "sync_list")
    store.save(["Documents"])

    ensure_client_config(settings)

    content = (settings.config_dir / "config").read_text()
    assert 'custom_option = "keep"' in content
    assert "sync_list" not in content
    assert scope_is_configured(settings, store)
