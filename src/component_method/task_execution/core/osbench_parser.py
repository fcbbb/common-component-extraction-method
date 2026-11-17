"""Run dataset-supplied OS-Bench log parsers outside the evaluator process.

OS-Bench tasks embed a Python ``parser(log)`` function in the dataset.  That
source is untrusted input: executing it in the evaluator process would let a
tampered dataset read or modify host state through the evaluator's privileges.
This module keeps the parser semantics but executes it in an isolated Python
subprocess with a small environment, resource limits, a wall-clock timeout and
size caps, and it only accepts a JSON object back.

The subprocess still runs with the invoking user's credentials, so this bounds
the blast radius rather than replacing full container isolation.
"""

from __future__ import annotations

import json
import os
from subprocess import TimeoutExpired, run as _run_process
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


PARSER_TIMEOUT_SECONDS = 60
MAX_SOURCE_BYTES = 256 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024

_RUNNER = r"""
import contextlib
import json
import sys

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX platforms
    resource = None

if resource is not None:
    for name, value in (
        ("RLIMIT_CPU", 30),
        ("RLIMIT_AS", 2 * 1024 ** 3),
        ("RLIMIT_FSIZE", 64 * 1024 ** 2),
        ("RLIMIT_CORE", 0),
        ("RLIMIT_NPROC", 64),
    ):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (OSError, ValueError):
            pass

source = sys.stdin.read()
with contextlib.redirect_stdout(sys.stderr):
    namespace = {"__name__": "osbench_log_parser"}
    exec(compile(source, "<osbench-log-parser>", "exec"), namespace)
    parser = namespace.get("parser")
    if not callable(parser):
        raise SystemExit("OS-Bench log_parser_source must define parser(log)")
    with open(sys.argv[1], encoding="utf-8", errors="replace") as handle:
        result = parser(handle.read())
if not isinstance(result, dict):
    raise SystemExit("OS-Bench log parser must return a dict")
sys.stdout.write(json.dumps(result))
"""


def _parser_environment(directory: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": directory,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def load_inline_parser(source: Any) -> Callable[[str], dict[str, Any]]:
    """Return a callable that runs the dataset parser in a bounded subprocess."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("OS-Bench log_parser_source is missing")
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError("OS-Bench log_parser_source is too large")
    try:
        compile(source, "<osbench-log-parser>", "exec")
    except SyntaxError as exc:
        raise ValueError(f"OS-Bench log_parser_source is invalid: {exc}") from exc

    def parse(log: str) -> dict[str, Any]:
        if len(log.encode("utf-8")) > MAX_LOG_BYTES:
            raise ValueError("OS-Bench test log is too large to parse")
        with tempfile.TemporaryDirectory(prefix="osbench-parser-") as directory:
            log_path = Path(directory) / "tests.log"
            log_path.write_text(log, encoding="utf-8")
            try:
                completed = _run_process(
                    [sys.executable, "-I", "-c", _RUNNER, str(log_path)],
                    input=source,
                    capture_output=True,
                    text=True,
                    timeout=PARSER_TIMEOUT_SECONDS,
                    cwd=directory,
                    env=_parser_environment(directory),
                    shell=False,
                )
            except TimeoutExpired as exc:
                raise ValueError("OS-Bench log parser timed out") from exc
            except OSError as exc:
                raise ValueError(f"could not start the OS-Bench log parser: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise ValueError(f"OS-Bench log parser failed: {detail or 'no output'}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OS-Bench log parser returned invalid JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise ValueError("OS-Bench log parser must return a dict")
        return result

    return parse