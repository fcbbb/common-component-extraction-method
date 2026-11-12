"""Evaluation adapter for OS-Bench cross-OS migration tasks.

OS-Bench differs from SWE-rebench in three important ways:

* the repository already contains the tests, so ``test_patch`` is normally empty;
* evaluation must run ``rebuild_cmd`` before ``test_cmd``;
* test output may be written to files and printed by ``print_cmd``;
* the dataset supplies an inline Python ``parser(log)`` function instead of a
  named parser in the vendored evaluator.

This module keeps that logic outside the SWE-rebench evaluator while reusing the
same Docker isolation, patch checks, and F2P/P2P accounting.
"""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import tempfile
import uuid
from typing import Any, Callable

import docker
from component_method.languages.task_environment import bundle_environment


STATUS_MARKER = "__OSBENCH_STATUS__"
PASS_STATUSES = {"pass", "passed", "ok", "true"}
FAIL_STATUSES = {"fail", "failed", "error", "false"}
SKIP_STATUSES = {"skip", "skipped", "notrun", "not run", "pending"}
DEFAULT_TIMEOUT_SECONDS = 3600


def _command_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a string or a list of strings")
    commands = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return commands


def _not_evaluated(task: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "instance_id": task["instance_id"],
        "evaluated": False,
        "error": reason,
        "passed_match": False,
        "required_tests_passed": False,
    }


def load_inline_parser(source: Any) -> Callable[[str], dict[str, Any]]:
    """Compile the dataset-provided parser function into a callable."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("OS-Bench log_parser_source is missing")
    namespace: dict[str, Any] = {}
    exec(compile(source, "<osbench-log-parser>", "exec"), namespace)  # noqa: S102
    parser = namespace.get("parser")
    if not callable(parser):
        raise ValueError("OS-Bench log_parser_source must define parser(log)")
    return parser


def _normalize_status(value: Any) -> str:
    if value is True:
        return "PASSED"
    if value is False:
        return "FAILED"
    text = str(value).strip().lower()
    if text in PASS_STATUSES:
        return "PASSED"
    if text in FAIL_STATUSES:
        return "FAILED"
    if text in SKIP_STATUSES:
        return "SKIPPED"
    return "UNKNOWN"


def _normalize_mapping(
    raw: Any, normalize_test_name: Callable[[str], str]
) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("OS-Bench parser must return a dict")
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        normalized[normalize_test_name(key)] = _normalize_status(value)
    return normalized


def _status_markers(log: str) -> dict[str, int | None]:
    markers: dict[str, int | None] = {}
    for line in log.splitlines():
        line = line.strip()
        if not line.startswith(STATUS_MARKER):
            continue
        payload = line[len(STATUS_MARKER):].strip()
        name, separator, value = payload.partition("=")
        if not separator:
            continue
        try:
            markers[name.strip().lower()] = int(value.strip())
        except ValueError:
            markers[name.strip().lower()] = None
    return markers


def _docker_script(
    task: dict[str, Any],
    patch: str,
    rebuild: list[str],
    tests: list[str],
    prints: list[str],
) -> str:
    apply = "git apply -v --3way --recount --ignore-space-change --whitespace=nowarn "
    commands = [
        "set -e",
        "test \"$(git rev-parse HEAD)\" = " + shlex.quote(task["base_commit"]),
        "git reset --hard HEAD",
    ]
    if patch:
        commands.append(apply + "/patches/source.patch")
    if task.get("test_patch"):
        commands.append(apply + "/patches/test.patch")
    commands.append("set +e")
    # Some OS-Bench images contain a stale build-tree source copy (for example
    # cppcheck's build/lib/pathmatch.cpp) that cmake's incremental build reuses
    # instead of the patched lib/ source.  Synchronize existing build-tree
    # source mirrors before rebuilding; this is a no-op for repositories that
    # do not use that layout.
    commands.append(
        'if [ -d build/lib ]; then '
        'for f in lib/*.cpp lib/*.h; do '
        '[ -e "$f" ] || continue; '
        '[ -e "build/$f" ] || continue; '
        'cmp -s "$f" "build/$f" || cp -f "$f" "build/$f"; '
        'done; fi'
    )
    commands.append(f"echo {STATUS_MARKER}REBUILD_BEGIN")
    commands.extend(rebuild)
    commands.append("rebuild_status=$?")
    commands.append(f"echo {STATUS_MARKER}REBUILD_STATUS=$rebuild_status")
    commands.append(f"echo {STATUS_MARKER}TEST_BEGIN")
    commands.extend(tests)
    commands.append("test_status=$?")
    commands.append(f"echo {STATUS_MARKER}TEST_STATUS=$test_status")
    commands.append(f"echo {STATUS_MARKER}PRINT_BEGIN")
    commands.extend(prints)
    commands.append("print_status=$?")
    commands.append(f"echo {STATUS_MARKER}PRINT_STATUS=$print_status")
    commands.append("exit $test_status")
    return "\n".join(commands)


def evaluate_osbench(
    task: dict[str, Any],
    patch: str,
    output: Path,
    bundle: Path | None = None,
    *,
    normalize_test_name: Callable[[str], str] | None = None,
    excluded: list[str] | None = None,
    expected_image_id: str | None = None,
) -> dict[str, Any]:
    """Run one OS-Bench patch through rebuild/test/print and parse the log."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    install = task.get("install_config") or {}
    rebuild = _command_list(install.get("rebuild_cmd"), "install_config.rebuild_cmd")
    tests = _command_list(install.get("test_cmd"), "install_config.test_cmd")
    prints = _command_list(install.get("print_cmd"), "install_config.print_cmd")
    if not tests:
        return _not_evaluated(task, "install_config.test_cmd is empty")
    parser_source = install.get("log_parser_source")
    try:
        parser = load_inline_parser(parser_source)
    except (ValueError, SyntaxError) as exc:
        return _not_evaluated(task, str(exc))
    normalize = normalize_test_name or (lambda value: value.strip())
    excluded_names = {normalize(value) for value in (excluded or [])}

    client = docker.from_env()
    image = client.images.get(task["image_name"]).id
    if expected_image_id is not None:
        assert image == expected_image_id, "official task image changed after preflight"
    timeout_seconds = int(install.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    name = "osbench-eval-" + uuid.uuid4().hex[:12]
    workdir = "/testbed"
    script = _docker_script(task, patch or "", rebuild, tests, prints)
    error: str | None = None
    exit_code = 1
    with tempfile.TemporaryDirectory(prefix="osbench-eval-") as directory:
        directory = Path(directory)
        directory.chmod(0o755)  # Container root has no DAC override after cap-drop=ALL.
        (directory / "source.patch").write_text(patch or "", encoding="utf-8")
        (directory / "test.patch").write_text(task.get("test_patch") or "", encoding="utf-8")
        args = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "-v",
            str(directory) + ":/patches:ro",
            "-w",
            workdir,
        ]
        if bundle is not None:
            args += [
                "-v",
                str(Path(bundle).resolve()) + ":" + workdir + "/component_bundle:ro",
            ]
            for key, value in bundle_environment(
                bundle,
                container_root=workdir + "/component_bundle",
                repository_root=workdir,
            ).items():
                args += ["-e", key + "=" + value]
        args += [image, "/bin/bash", "-c", script]
        try:
            with (output / "tests.log").open("w", encoding="utf-8") as handle:
                exit_code = subprocess.run(
                    args,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_seconds,
                ).returncode
        except subprocess.TimeoutExpired:
            exit_code, error = 124, "Evaluation process timed out"
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    log = (output / "tests.log").read_text(encoding="utf-8", errors="replace")
    markers = _status_markers(log)
    try:
        raw = parser(log)
        parsed = _normalize_mapping(raw, normalize)
    except BaseException as exc:  # parser is dataset-supplied
        parsed = {}
        error = error or f"OS-Bench log parser failed: {exc}"
    f2p = {normalize(name) for name in task.get("FAIL_TO_PASS", [])} - excluded_names
    p2p = {normalize(name) for name in task.get("PASS_TO_PASS", [])} - excluded_names
    expected = f2p | p2p
    expected_list = sorted(
        {
            normalize(name)
            for name in [*task.get("FAIL_TO_PASS", []), *task.get("PASS_TO_PASS", [])]
            if normalize(name) not in excluded_names
        }
    )
    passed = {name for name, status in parsed.items() if status == "PASSED"}
    if not expected.intersection(parsed):
        error = error or "No registered test outcomes; inspect tests.log for an infrastructure failure."
    rebuild_status = markers.get("rebuild_status")
    test_status = markers.get("test_status")
    print_status = markers.get("print_status")
    if rebuild_status not in {None, 0}:
        error = error or f"OS-Bench rebuild command failed with exit code {rebuild_status}."
    result = {
        "instance_id": task["instance_id"],
        "image": task["image_name"],
        "image_id": image,
        "network": "none",
        "evaluated": True,
        "exit_code": exit_code,
        "error": error,
        "F2P_passed": len(f2p & passed),
        "F2P_failed": sum(parsed.get(name) == "FAILED" for name in f2p),
        "F2P_total": len(f2p),
        "P2P_passed": len(p2p & passed),
        "P2P_total": len(p2p),
        "missing_required": sorted(expected - passed),
        "extra_passed": sorted(passed - expected),
        "passed_match": sorted(passed) == expected_list,
        "required_tests_passed": expected.issubset(passed),
        "rebuild_exit_code": rebuild_status,
        "test_exit_code": test_status,
        "print_exit_code": print_status,
    }
    if excluded:
        result["evaluation_adjustment"] = {
            "excluded_tests": list(excluded),
        }
    return result


def is_osbench_task(task: dict[str, Any]) -> bool:
    install = task.get("install_config") or {}
    return (
        task.get("task_type") == "cross_platform_migration"
        or install.get("log_parser") == "osbench_inline"
        or ("rebuild_cmd" in install and "print_cmd" in install)
    )