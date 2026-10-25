from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def locked_json(path: Path) -> Iterator[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                data = {}
            yield data
            _atomic_write(path, data)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
