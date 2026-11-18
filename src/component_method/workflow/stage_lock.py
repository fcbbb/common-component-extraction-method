#!/usr/bin/env python3
"""Run one stage command while holding the task's stage lock.

Synchronous kernel calls take the lock non-blockingly and report ``STAGE_BUSY``.
Job stages outlive the kernel process that started them, so the lock must be
held by the job process itself; otherwise two background stages (or a job and a
synchronous call) could write the same task root concurrently.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys


def _install_forwarding(
    child_box: list[subprocess.Popen | None],
    pending: list[int],
) -> None:
    """Pass cancellation signals to the real stage process.

    ``job_cancel`` signals the pid it recorded, which is this wrapper. Signals
    that arrive between installing the handlers and spawning the child are
    queued and delivered as soon as the child exists.
    """
    def handler(signum, frame):  # noqa: ANN001, ARG001 - signal signature
        child = child_box[0]
        if child is None:
            pending.append(signum)
            return
        try:
            child.send_signal(signum)
        except OSError:
            pass

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" not in arguments:
        print("stage_lock: missing -- before the command", file=sys.stderr)
        return 2
    separator = arguments.index("--")
    options, command = arguments[:separator], arguments[separator + 1 :]
    if not command:
        print("stage_lock: empty command", file=sys.stderr)
        return 2
    lock_root = None
    index = 0
    while index < len(options):
        option = options[index]
        if option == "--lock-root" and index + 1 < len(options):
            lock_root = Path(options[index + 1]).expanduser().resolve()
            index += 2
            continue
        print(f"stage_lock: unknown argument {option!r}", file=sys.stderr)
        return 2
    if lock_root is None:
        print("stage_lock: --lock-root is required", file=sys.stderr)
        return 2

    lock_root.mkdir(parents=True, exist_ok=True)
    with (lock_root / ".dsh_stage.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        child_box: list[subprocess.Popen | None] = [None]
        pending: list[int] = []
        _install_forwarding(child_box, pending)
        child = subprocess.Popen(command, env=os.environ)
        child_box[0] = child
        for signum in pending:
            try:
                child.send_signal(signum)
            except OSError:
                pass
        try:
            return child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    raise SystemExit(main())