from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .storage import write_lines_atomic


def normalize_paths(paths: list[str]) -> list[str]:
    cleaned: set[str] = set()
    for path in paths:
        if not path or path.startswith("/") or "\\" in path or any(char in path for char in "\x00\r\n"):
            raise ValueError("Folder paths must be non-empty relative OneDrive paths.")
        parts = path.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("Folder paths contain an unsafe segment.")
        cleaned.add(path)
    ordered = sorted(cleaned, key=lambda value: (value.count("/"), value.casefold()))
    result: list[str] = []
    for path in ordered:
        if not any(path == parent or path.startswith(parent + "/") for parent in result):
            result.append(path)
    return result


@dataclass
class SelectionStore:
    path: Path
    revision: int = 0
    selected: list[str] | None = None

    def load(self) -> list[str]:
        if self.selected is None:
            try:
                self.selected = normalize_paths([line.strip() for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()])
            except FileNotFoundError:
                self.selected = []
        return self.selected

    def save(self, paths: list[str]) -> list[str]:
        normal = normalize_paths(paths)
        if not normal:
            raise ValueError("Choose at least one folder; an empty sync scope is not allowed.")
        write_lines_atomic(self.path, normal)
        self.selected = normal
        self.revision += 1
        return normal
