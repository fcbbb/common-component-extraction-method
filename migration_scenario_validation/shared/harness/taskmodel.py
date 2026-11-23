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


_AGENT_BUILD_REPLACEMENTS = (
    ("-DENABLE_TESTS=ON", "-DENABLE_TESTS=OFF"),
    ("-DBUILD_TESTS=ON", "-DBUILD_TESTS=OFF"),
    ("-DBUILD_TESTING=ON", "-DBUILD_TESTING=OFF"),
    ("-DENABLE_TESTING=ON", "-DENABLE_TESTING=OFF"),
    ("-DENABLE_TEST=ON", "-DENABLE_TEST=OFF"),
)


def agent_build_command(task: Dict[str, Any]) -> Optional[str]:
    """Return the build command shown to the agent.

    The judge build may compile upstream tests; the agent-visible tree has
    those tests removed.  Tasks can supply an explicit ``agent_build.command``;
    otherwise the common CMake test switches are turned off.
    """
    explicit = task.get("agent_build")
    if isinstance(explicit, str):
        command = explicit
    elif isinstance(explicit, dict) and explicit.get("command"):
        command = str(explicit["command"])
    else:
        command = command_of(task, "build") or ""
    for old, new in _AGENT_BUILD_REPLACEMENTS:
        command = command.replace(old, new)
    return command


def target_api_gate(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the positive target-API gate for a task.

    A negative ``api_removal`` gate only says what must disappear.  Without a
    positive gate a one-shot model can replace the target implementation with
    a portable fallback and still pass.  The gate is task-specific because the
    target API differs across scenarios.
    """
    gates = task.get("gates") or {}
    if isinstance(gates, dict) and isinstance(gates.get("target_api"), dict):
        return dict(gates["target_api"])

    scenario = str(task.get("scenario") or "")
    task_id = str(task.get("task_id") or "")
    if scenario == "ipp_to_vsipl":
        # fit C means VSIPL has no matching primitive (for example the IIR
        # negative-control task); a hand-written implementation is the task.
        if str(task.get("fit") or "") == "C" or task_id == "l3_iir_eq_negative":
            return None
        return {
            "symbol_regex": r"^vsip_",
            "source_dirs": ["src"],
            "source_regex": r"\bvsip_[A-Za-z0-9_]+\b",
            "min_hits": 1,
        }

    if scenario == "windows_to_kylin":
        if task_id == "negative_win32_eventlog":
            return None
        api = gates.get("api_removal") if isinstance(gates, dict) else None
        dirs = list(api.get("source_dirs") or []) if isinstance(api, dict) else []
        if not dirs:
            dirs = ["src"]
        if task_id.endswith("curl_build"):
            regex = r"(?i)\b(?:cmake|configure|make)\b"
        elif "curl_tls" in task_id:
            regex = r"\b(?:SSL_|OPENSSL_|EVP_)[A-Za-z0-9_]+"
        elif "opencv" in task_id:
            regex = r"\b(?:gtk_|gdk_)[A-Za-z0-9_]+"
        elif "nginx" in task_id:
            regex = r"\bngx_[A-Za-z0-9_]+"
        else:
            # POSIX layer used by Poco/libarchive/libgit2/libuv.
            regex = (
                r"\b(?:pthread_[A-Za-z0-9_]+|dlopen|dlsym|dlclose|"
                r"open|read|write|stat|unlink|mkdir|rename|opendir|readdir|"
                r"fork|execve|epoll_[A-Za-z0-9_]+|sem_[A-Za-z0-9_]+)"
            )
        return {
            "source_dirs": dirs,
            "source_regex": regex,
            "min_hits": 1,
        }
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
    # WSL has a small fixed RAM budget; an unbounded `cmake --build -j`
    # can OOM the whole VM.  Callers may override these, but the safe
    # default is deliberately low.
    merged.setdefault("CMAKE_BUILD_PARALLEL_LEVEL", "2")
    merged.setdefault("MAKEFLAGS", "-j2")
    merged.setdefault("NINJAFLAGS", "-j2")
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