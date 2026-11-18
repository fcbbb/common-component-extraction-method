"""Small local job manager for long-running method stages.

Jobs are deliberately OS-process based rather than in-memory futures: the DSH
plugin can return a job id immediately, and a later tool call can inspect the
same status directory even after the tool call that started it returns.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from typing import Any, Mapping, Sequence

JOB_SCHEMA = "component-method-dsh-job-v1"
TERMINAL = {"succeeded", "failed", "cancelled"}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _new_job_id(method: str) -> str:
    safe = "".join(char if char.isalnum() or char in "_-" else "-" for char in method)
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{safe[:40]}-{uuid.uuid4().hex[:8]}"


def start_job(
    *,
    job_root: Path,
    method: str,
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a detached stage process and return its durable status record."""
    job_root = job_root.expanduser().resolve()
    job_root.mkdir(parents=True, exist_ok=True)
    job_id = _new_job_id(method)
    directory = job_root / job_id
    directory.mkdir(parents=True, exist_ok=False)
    stdout = directory / "stdout.log"
    stderr = directory / "stderr.log"
    status_path = directory / "status.json"
    command = [str(part) for part in command]
    _write(
        directory / "command.json",
        {
            "schema": JOB_SCHEMA,
            "job_id": job_id,
            "method": method,
            "command": command,
            "cwd": str(cwd),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "context": dict(context or {}),
        },
    )
    # The caller is not durable: the DSH kernel prints the job id and exits, so
    # a monitor thread here would die with it and the status would stay
    # "running" forever.  The job runs under a supervisor that owns the status
    # file instead.
    supervised = [
        sys.executable,
        "-m",
        "component_method.dsh_job_runner",
        "--status",
        str(status_path),
        "--",
        *command,
    ]
    status = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "method": method,
        "status": "running",
        "pid": None,
        "exit_code": None,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "finished_at": None,
        "context": dict(context or {}),
    }
    _write(status_path, status)
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.Popen(
                supervised,
                cwd=str(cwd),
                env=dict(environment or {}),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                shell=False,
            )
    except OSError as exc:
        status.update(status="failed", error=str(exc), finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        _write(status_path, status)
        return status
    status["pid"] = process.pid
    _write(status_path, status)
    return status


def job_status(job_root: Path, job_id: str, *, log_bytes: int = 8000) -> dict[str, Any]:
    _safe_job_id(job_id)
    directory = job_root.expanduser().resolve() / job_id
    status = _read(directory / "status.json")
    if status is None:
        return {"schema": JOB_SCHEMA, "job_id": job_id, "status": "missing"}
    for name in ("stdout", "stderr"):
        path = directory / f"{name}.log"
        if path.is_file():
            data = path.read_bytes()
            status[f"{name}_tail"] = data[-max(0, log_bytes):].decode("utf-8", errors="replace")
    status["job_dir"] = str(directory)
    return status


def job_cancel(job_root: Path, job_id: str) -> dict[str, Any]:
    _safe_job_id(job_id)
    directory = job_root.expanduser().resolve() / job_id
    status = _read(directory / "status.json")
    if status is None:
        return {"schema": JOB_SCHEMA, "job_id": job_id, "status": "missing"}
    if status.get("status") in TERMINAL:
        return status
    pid = status.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    status.update(status="cancelled", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    _write(directory / "status.json", status)
    return status


def _safe_job_id(value: str) -> None:
    if not isinstance(value, str) or not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in value):
        raise ValueError("invalid job_id")
