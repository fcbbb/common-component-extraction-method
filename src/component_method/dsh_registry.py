"""Run registry and path authority for the DSH method tools.

The model never supplies host paths.  A controller writes one registry document
before starting DSH, and the kernel resolves run/task identities through it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

SCHEMA = "component-method-dsh-registry-v1"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


class RegistryError(ValueError):
    """Raised when a run or task is not available to this DSH session."""


def _check_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{field} must be a non-empty string")
    pattern = RUN_ID_RE if field == "run_id" else TASK_ID_RE
    if not pattern.fullmatch(value):
        raise RegistryError(f"{field} contains unsupported characters")
    return value


def load_registry(path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate the controller-owned registry.

    An empty registry is returned when no path is configured.  In that mode the
    kernel refuses all run-scoped methods; this keeps accidental host execution
    from becoming the default.
    """
    configured = path or os.environ.get("COMPONENT_DSH_RUN_REGISTRY")
    if not configured:
        return {"schema": SCHEMA, "runs": {}}
    registry_path = Path(configured).expanduser().resolve()
    if not registry_path.is_file():
        raise RegistryError(f"run registry does not exist: {registry_path}")
    try:
        value = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"invalid run registry JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise RegistryError(f"unsupported run registry schema: {value.get('schema')!r}")
    runs = value.get("runs")
    if not isinstance(runs, dict):
        raise RegistryError("run registry runs must be an object")
    return value


def resolve_run(
    registry: dict[str, Any],
    run_id: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Resolve one run and optional task to trusted host paths."""
    run_key = _check_id(run_id, field="run_id")
    run = registry.get("runs", {}).get(run_key)
    if not isinstance(run, dict):
        raise RegistryError(f"run is not registered: {run_key}")
    run_root = run.get("run_root")
    if not isinstance(run_root, str) or not run_root:
        raise RegistryError(f"run has no run_root: {run_key}")
    root = Path(run_root).expanduser().resolve()
    if not root.is_dir():
        raise RegistryError(f"run_root does not exist: {root}")
    tasks = run.get("tasks", {})
    if not isinstance(tasks, dict):
        raise RegistryError(f"run tasks must be an object: {run_key}")
    selected = task_id or run.get("task_id")
    task_root = None
    repository = None
    if selected is not None:
        task_key = _check_id(selected, field="task_id")
        task = tasks.get(task_key)
        if not isinstance(task, dict):
            raise RegistryError(f"task is not registered: {task_key}")
        task_root_value = task.get("task_root")
        repository_value = task.get("repository")
        if not isinstance(task_root_value, str) or not task_root_value:
            raise RegistryError(f"task has no task_root: {task_key}")
        task_root = Path(task_root_value).expanduser().resolve()
        if not task_root.is_dir():
            raise RegistryError(f"task_root does not exist: {task_root}")
        if repository_value is not None:
            if not isinstance(repository_value, str) or not repository_value:
                raise RegistryError(f"task repository is invalid: {task_key}")
            repository = Path(repository_value).expanduser().resolve()
            if not repository.is_dir():
                raise RegistryError(f"repository does not exist: {repository}")
    return {
        "run_id": run_key,
        "task_id": selected,
        "run_root": root,
        "task_root": task_root,
        "repository": repository,
        "run": run,
        "task": tasks.get(selected) if selected is not None else None,
    }


def registry_from_environment() -> dict[str, Any]:
    return load_registry()
