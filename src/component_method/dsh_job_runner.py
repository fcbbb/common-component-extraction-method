"""Run one background job command and record its terminal status.

``dsh_jobs.start_job`` must return as soon as the job is spawned, so the
process that starts a job cannot be the one that waits for it.  In the DSH
kernel that process exits immediately after printing the job id; a monitor
thread there would die with it and ``status.json`` would stay ``running``
forever.  This supervisor is the job itself: it forwards termination signals
to the stage and writes the terminal status when the stage exits.

    python -m component_method.dsh_job_runner --status <status.json> -- <command...>

The exit code is the stage's, so ``job_cancel`` and the status record agree.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" not in arguments:
        print("dsh_job_runner: missing -- before the command", file=sys.stderr)
        return 2
    separator = arguments.index("--")
    options, command = arguments[:separator], arguments[separator + 1 :]
    if not command:
        print("dsh_job_runner: empty command", file=sys.stderr)
        return 2
    status_path = None
    index = 0
    while index < len(options):
        if options[index] == "--status" and index + 1 < len(options):
            status_path = Path(options[index + 1])
            index += 2
            continue
        print(f"dsh_job_runner: unknown argument {options[index]!r}", file=sys.stderr)
        return 2
    if status_path is None:
        print("dsh_job_runner: --status is required", file=sys.stderr)
        return 2

    child_box: list[subprocess.Popen | None] = [None]

    def handler(signum, frame):  # noqa: ANN001, ARG001 - signal signature
        child = child_box[0]
        if child is None:
            return
        try:
            child.send_signal(signum)
        except OSError:
            pass

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    process = subprocess.Popen(command, env=dict(os.environ))
    child_box[0] = process
    return_code = process.wait()

    status = _read(status_path)
    if status.get("status") == "cancelled":
        # job_cancel already recorded the outcome; keep it and note the exit.
        status["exit_code"] = return_code
        status["finished_at"] = _now()
    else:
        status.update(
            status="succeeded" if return_code == 0 else "failed",
            exit_code=return_code,
            finished_at=_now(),
        )
    _write(status_path, status)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())