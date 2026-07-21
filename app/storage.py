from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_json_private(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as temporary:
        json.dump(value, temporary)
        temporary.write("\n")
        temporary_name = temporary.name
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, path)


def read_json(path: Path, default: object) -> object:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_lines_atomic(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as temporary:
        temporary.write("\n".join(lines))
        temporary.write("\n" if lines else "")
        temporary_name = temporary.name
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, path)
