"""Share completed region extraction only for identical visible workspaces."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


CACHE_SCHEMA = 1


def cache_identity(
    *,
    primary_files: list[str],
    context_files: list[str],
    sources: dict[str, str],
    task: str,
    model: str | None,
    recipe_key: str,
) -> tuple[str, dict[str, Any]]:
    """Include every file the isolated agent can read, plus its exact instructions."""
    files = sorted(set(primary_files) | set(context_files))
    inputs = {
        "schema": CACHE_SCHEMA,
        "recipe_key": recipe_key,
        "model": model,
        "task": task,
        "primary_files": primary_files,
        "context_files": context_files,
        "files": {
            file_id: hashlib.sha256(sources[file_id].encode("utf-8")).hexdigest()
            for file_id in files
        },
    }
    encoded = json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), inputs


@contextmanager
def locked_entry(cache_root: Path, key: str) -> Iterator[Path]:
    """Serialize identical concurrent tasks without blocking other regions."""
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / f"{key}.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield cache_root / f"{key}.json"
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def load_entry(path: Path, inputs: dict[str, Any]) -> dict[str, Any] | None:
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or entry.get("inputs") != inputs:
        return None
    response = entry.get("response")
    return response if isinstance(response, dict) else None


def save_entry(path: Path, inputs: dict[str, Any], response: dict[str, Any]) -> None:
    """Publish only a completed response; readers never observe partial JSON."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}-",
        suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump({"inputs": inputs, "response": response}, handle, ensure_ascii=False)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
