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
    _validate_registry_document(value)
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


def _validate_registry_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        schema = value.get("schema") if isinstance(value, dict) else None
        raise RegistryError(f"unsupported run registry schema: {schema!r}")
    runs = value.get("runs")
    if not isinstance(runs, dict):
        raise RegistryError("run registry runs must be an object")
    for run_id, run in runs.items():
        _check_id(run_id, field="run_id")
        if not isinstance(run, dict):
            raise RegistryError(f"run must be an object: {run_id}")
        if not isinstance(run.get("run_root"), str) or not run["run_root"]:
            raise RegistryError(f"run has no run_root: {run_id}")
        if run.get("embedding_dir") is not None and not isinstance(run["embedding_dir"], str):
            raise RegistryError(f"run embedding_dir must be a string: {run_id}")
        tasks = run.get("tasks", {})
        if not isinstance(tasks, dict):
            raise RegistryError(f"run tasks must be an object: {run_id}")
        for task_id, task in tasks.items():
            _check_id(task_id, field="task_id")
            if not isinstance(task, dict):
                raise RegistryError(f"task must be an object: {task_id}")
            if not isinstance(task.get("task_root"), str) or not task["task_root"]:
                raise RegistryError(f"task has no task_root: {task_id}")
            if task.get("repository") is not None and (
                not isinstance(task["repository"], str) or not task["repository"]
            ):
                raise RegistryError(f"task repository is invalid: {task_id}")
    return value


def empty_registry() -> dict[str, Any]:
    return {"schema": SCHEMA, "runs": {}}


def _registry_path(path: Path | str | None) -> Path:
    configured = path or os.environ.get("COMPONENT_DSH_RUN_REGISTRY")
    if not configured:
        raise RegistryError(
            "run registry path is not configured; pass --registry or set "
            "COMPONENT_DSH_RUN_REGISTRY"
        )
    return Path(configured).expanduser().resolve()


def write_registry(registry: dict[str, Any], path: Path | str | None = None) -> Path:
    """Validate and atomically write a controller-owned registry document."""
    _validate_registry_document(registry)
    target = _registry_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return target


def register_run(
    registry: dict[str, Any],
    run_id: str,
    run_root: Path | str,
    *,
    embedding_dir: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Add or replace one run entry in a registry document."""
    key = _check_id(run_id, field="run_id")
    existing = registry.setdefault("runs", {}).get(key)
    tasks = existing.get("tasks", {}) if isinstance(existing, dict) else {}
    run: dict[str, Any] = {
        "run_root": str(Path(run_root).expanduser().resolve()),
        "tasks": dict(tasks) if isinstance(tasks, dict) else {},
    }
    if task_id is None and isinstance(existing, dict):
        task_id = existing.get("task_id")
    if task_id is not None:
        run["task_id"] = _check_id(task_id, field="task_id")
    if embedding_dir is not None:
        if not isinstance(embedding_dir, str) or not embedding_dir.strip():
            raise RegistryError("embedding_dir must be a non-empty string")
        run["embedding_dir"] = embedding_dir
    registry.setdefault("runs", {})[key] = run
    return registry


def register_task(
    registry: dict[str, Any],
    run_id: str,
    task_id: str,
    task_root: Path | str,
    *,
    repository: Path | str | None = None,
) -> dict[str, Any]:
    """Add or replace one task entry inside an existing run."""
    run_key = _check_id(run_id, field="run_id")
    task_key = _check_id(task_id, field="task_id")
    run = registry.get("runs", {}).get(run_key)
    if not isinstance(run, dict):
        raise RegistryError(f"run is not registered: {run_key}")
    task: dict[str, Any] = {"task_root": str(Path(task_root).expanduser().resolve())}
    if repository is not None:
        task["repository"] = str(Path(repository).expanduser().resolve())
    run.setdefault("tasks", {})[task_key] = task
    return registry


def _read_registry_for_update(path: Path, *, create: bool) -> dict[str, Any]:
    if path.is_file():
        return load_registry(path)
    if not create:
        raise RegistryError(f"run registry does not exist: {path}")
    return empty_registry()


def main(argv: list[str] | None = None) -> int:
    """Create and edit the run registry before starting a DSH session."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create an empty registry")
    add_run = commands.add_parser("add-run", help="add or replace a run entry")
    add_task = commands.add_parser("add-task", help="add or replace a task entry")
    validate = commands.add_parser("validate", help="validate an existing registry")
    for command in (init, add_run, add_task, validate):
        command.add_argument("--registry", type=Path, default=None)
    init.add_argument("--force", action="store_true")
    add_run.add_argument("--run-id", required=True)
    add_run.add_argument("--run-root", type=Path, required=True)
    add_run.add_argument("--embedding-dir", default=None)
    add_run.add_argument("--task-id", default=None)
    add_task.add_argument("--run-id", required=True)
    add_task.add_argument("--task-id", required=True)
    add_task.add_argument("--task-root", type=Path, required=True)
    add_task.add_argument("--repository", type=Path, default=None)
    args = parser.parse_args(argv)

    target = _registry_path(args.registry)
    if args.command == "init":
        if target.exists() and not args.force:
            raise RegistryError(f"run registry already exists: {target}")
        write_registry(empty_registry(), target)
    elif args.command == "add-run":
        registry = _read_registry_for_update(target, create=True)
        register_run(
            registry,
            args.run_id,
            args.run_root,
            embedding_dir=args.embedding_dir,
            task_id=args.task_id,
        )
        write_registry(registry, target)
    elif args.command == "add-task":
        registry = _read_registry_for_update(target, create=False)
        register_task(
            registry,
            args.run_id,
            args.task_id,
            args.task_root,
            repository=args.repository,
        )
        write_registry(registry, target)
    else:
        load_registry(target)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
