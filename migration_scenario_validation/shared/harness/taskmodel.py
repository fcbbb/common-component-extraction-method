#!/usr/bin/env python3
"""Task model shared by all migration scenarios.

A task package is described by ``task.yaml`` at its root.  The schema is
intentionally small and stable across scenarios:

  task_id, scenario, level, source, target, spec, build, hidden_tests, gates

Scenario-specific keys (``fit``, ``source_kind``, ``negative`` ...) are allowed
and preserved.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import yaml

REQUIRED_KEYS = (
    "task_id",
    "scenario",
    "level",
    "source",
    "target",
    "spec",
    "build",
    "hidden_tests",
    "gates",
)


def load_task(root: os.PathLike | str) -> Dict[str, Any]:
    """Load ``<root>/task.yaml`` and return a dict with ``_root`` set."""
    root = Path(root).resolve()
    path = root / "task.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"task.yaml not found under {root}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: task.yaml must contain a mapping")
    data["_root"] = str(root)
    return data


def dump_task(task: Dict[str, Any], path: os.PathLike | str) -> None:
    data = {k: v for k, v in task.items() if not k.startswith("_")}
    with Path(path).open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)


def root_of(task: Dict[str, Any]) -> Path:
    return Path(task["_root"])


def task_id(task: Dict[str, Any]) -> str:
    return str(task.get("task_id") or root_of(task).name)


def work_dir(task: Dict[str, Any], override: Optional[str] = None) -> Path:
    if override:
        return Path(override).resolve()
    candidate = root_of(task) / "work"
    return candidate if candidate.is_dir() else root_of(task)


def build_dir(task: Dict[str, Any], override: Optional[str] = None) -> Path:
    if override:
        return Path(override).resolve()
    candidate = root_of(task) / "build"
    return candidate


def golden_dir(task: Dict[str, Any], override: Optional[str] = None) -> Path:
    if override:
        return Path(override).resolve()
    return root_of(task) / "harness" / "golden"


def _get(mapping: Any, *keys: str, default: Any = None) -> Any:
    cur = mapping
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def command_of(task: Dict[str, Any], section: str) -> Optional[str]:
    """Return a command string from a task section.

    Accepts either ``section: "cmd"`` or ``section: {command: "cmd"}``.
    """
    value = task.get(section)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        cmd = value.get("command")
        return str(cmd) if cmd else None
    return None


def expand_command(
    command: str,
    *,
    root: Path,
    work: Path,
    build: Path,
    golden: Path,
    extra: Optional[Dict[str, str]] = None,
) -> str:
    """Replace harness placeholders with absolute paths.

    Supported placeholders: ``{root}``, ``{work}``, ``{build}``, ``{golden}``
    and any key in ``extra``.
    """
    mapping = {
        "{root}": str(root),
        "{work}": str(work),
        "{build}": str(build),
        "{golden}": str(golden),
    }
    if extra:
        mapping.update({f"{{{k}}}": str(v) for k, v in extra.items()})
    out = command
    for key, value in mapping.items():
        out = out.replace(key, value)
    return out


def run_command(
    command: str,
    *,
    cwd: Path,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 3600,
) -> Tuple[int, str]:
    """Run a shell command and return ``(returncode, combined_output)``."""
    merged = os.environ.copy()
    if env:
        merged.update({str(k): str(v) for k, v in env.items()})
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=merged,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out + f"\n[timeout after {timeout}s]"


def parse_summary(output: str) -> Dict[str, Any]:
    """Extract the common ``SUMMARY cases=... failures=...`` line."""
    result: Dict[str, Any] = {}
    m = re.search(r"SUMMARY\s+cases=(\d+)\s+failures=(\d+)", output)
    if m:
        result["cases"] = int(m.group(1))
        result["failures"] = int(m.group(2))
    m = re.search(r"worst_rel=([0-9.eE+-]+)", output)
    if m:
        try:
            result["worst_rel"] = float(m.group(1))
        except ValueError:
            pass
    return result


def iter_task_dirs(parent: os.PathLike | str) -> Iterable[Path]:
    parent = Path(parent)
    if not parent.is_dir():
        return
    for child in sorted(parent.iterdir()):
        if child.is_dir() and (child / "task.yaml").is_file():
            yield child