#!/usr/bin/env python3
"""刷新当前独立发布包的文件清单和 SHA-256。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
RELEASE = REPOSITORY.parent
OFFLINE = RELEASE / "offline_artifacts"
GENERATED_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "work",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest(root: Path, excluded: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path == excluded
            or path.is_symlink()
            or any(part in GENERATED_DIRECTORIES for part in path.relative_to(root).parts)
            or any(part.endswith(".egg-info") for part in path.relative_to(root).parts)
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    task_ids = [
        row["instance_id"]
        for row in json.loads(
            (REPOSITORY / "config" / "release_tasks.json").read_text(encoding="utf-8")
        )["tasks"]
    ]
    repository_manifest = REPOSITORY / "results" / "manifest.json"
    write_json(
        repository_manifest,
        {
            "schema": "common-component-repository-manifest-v1",
            "task_ids": task_ids,
            "files": file_manifest(REPOSITORY, repository_manifest),
        },
    )
    offline_manifest = OFFLINE / "manifest.json"
    current = json.loads(offline_manifest.read_text(encoding="utf-8"))
    write_json(
        offline_manifest,
        {
            **{key: value for key, value in current.items() if key != "files"},
            "files": file_manifest(OFFLINE, offline_manifest),
        },
    )
    print("发布包清单已刷新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
