"""Resolve release-local paths without depending on the original workspace."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]


def release_root() -> Path:
    configured = os.environ.get("COMPONENT_METHOD_RELEASE_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = REPOSITORY_ROOT.parent
    if not (root / "repository").is_dir() or not (root / "offline_artifacts").is_dir():
        raise RuntimeError(
            "cannot locate the release root; set COMPONENT_METHOD_RELEASE_ROOT to "
            "the directory containing repository/ and offline_artifacts/"
        )
    return root


def resolve_release_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (release_root() / path).resolve()


def offline_task_root(task_id: str) -> Path:
    root = release_root() / "offline_artifacts" / "tasks" / task_id
    if not root.is_dir():
        raise RuntimeError(f"offline task does not exist: {task_id}")
    return root


def task_execution_root() -> Path:
    return PACKAGE_ROOT / "task_execution"
