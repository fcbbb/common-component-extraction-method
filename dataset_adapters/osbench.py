"""Prepare OS-Bench cross-OS migration tasks for the component pipeline.

OS-Bench is a different task family from SWE-rebench:

* tasks ask for a repository-wide Windows-to-Linux migration;
* tests already exist in the repository (``test_patch`` is normally empty);
* evaluation runs ``rebuild_cmds`` and ``test_cmds`` and prints logs with
  ``print_cmds``;
* each row ships an inline Python ``log_parser`` function.

This module only performs the *preparation* boundary.  It validates the JSONL
rows, extracts the task repository from the official/prepared Docker image,
generates a normalized compilation database for the C++ backend, and writes the
offline task package plus a writable component-method workspace.  It does not
run component extraction, retrieval, or task inference.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "osbench-task-v1"
WORKSPACE_SCHEMA = "component-method-osbench-workspace-v1"
TASK_SCHEMA = "component-method-osbench-task-v1"
PROVENANCE_SCHEMA = "osbench-task-provenance-v1"
PREPARATION_SCHEMA = "osbench-preparation-v1"
PUBLIC_TASK_SCHEMA = "osbench-task-public-v1"
PRIVATE_TASK_SCHEMA = "osbench-task-private-v1"

SUPPORTED_LANGUAGES = {"cpp"}
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
SCAN_EXCLUDED_DIRECTORIES = {
    ".git", "build", "dist", "vendor", "third_party", "generated", "tests", "test",
}
PRUNE_DIRECTORIES = {
    ".git", "build", "reports", "mnt_tmp", "tmp", "node_modules", ".cache",
    "CMakeFiles", ".pytest_cache", "__pycache__",
}
PRUNE_FILES = {"test-output.log", "ctest-output.log", "ctest-verbose.log"}
CONTAINER_REPOSITORY = "/testbed"
# OS-Bench images declare /testbed/mnt_tmp as a Docker VOLUME.  The component
# runner bind-mounts the source snapshot at /testbed and runs with a read-only
# root filesystem, so Docker needs this mountpoint to exist in the bind source.
IMAGE_VOLUME_DIRECTORIES = ("mnt_tmp",)

REQUIRED_FIELDS = (
    "instance_id",
    "repo",
    "language",
    "base_commit",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "difficulty",
    "docker_image",
    "log_parser",
    "metadata",
    "migration_direction",
    "patch",
    "print_cmds",
    "problem_statement",
    "rebuild_cmds",
    "test_cmds",
    "test_patch",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run(
    arguments: Iterable[str],
    *,
    check: bool = True,
    timeout: int = 900,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [str(item) for item in arguments]
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{detail[-4000:]}"
        )
    return result


def _required_string(value: Any, field: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_string_list(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
    minimum: int = 1,
) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{field} must be {qualifier}")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or len(item.strip()) < minimum:
            raise ValueError(f"{field}[{index}] must be a non-empty string")
        result.append(item.strip())
    return result


def _validate_log_parser(source: str) -> None:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("log_parser must be a non-empty Python function source")
    try:
        tree = ast.parse(source, filename="<osbench-log-parser>")
    except SyntaxError as exc:
        raise ValueError(f"log_parser is not valid Python: {exc}") from exc
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "parser" not in functions:
        raise ValueError("log_parser must define a top-level function named parser")


def normalize_row(row: dict[str, Any], *, line_number: int = 0) -> dict[str, Any]:
    """Validate one OS-Bench row and return a normalized copy."""
    if not isinstance(row, dict):
        raise ValueError(f"row {line_number} is not a JSON object")
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
        raise ValueError(f"row {line_number} is missing fields: {missing}")
    normalized = dict(row)
    normalized["instance_id"] = _required_string(row["instance_id"], "instance_id")
    normalized["repo"] = _required_string(row["repo"], "repo")
    if "/" not in normalized["repo"]:
        raise ValueError(f"row {line_number} repo must be owner/name")
    normalized["language"] = _required_string(row["language"], "language").lower()
    if normalized["language"] not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"row {line_number} language {normalized['language']!r} is not supported; "
            f"the current preparation adapter supports {sorted(SUPPORTED_LANGUAGES)}"
        )
    normalized["base_commit"] = _required_string(row["base_commit"], "base_commit").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized["base_commit"]):
        raise ValueError(f"row {line_number} base_commit must be a full lowercase Git SHA")
    normalized["docker_image"] = _required_string(row["docker_image"], "docker_image")
    normalized["problem_statement"] = _required_string(
        row["problem_statement"], "problem_statement", minimum=10
    )
    normalized["migration_direction"] = _required_string(
        row["migration_direction"], "migration_direction"
    )
    normalized["FAIL_TO_PASS"] = _required_string_list(
        row["FAIL_TO_PASS"], "FAIL_TO_PASS"
    )
    normalized["PASS_TO_PASS"] = _required_string_list(
        row["PASS_TO_PASS"], "PASS_TO_PASS", allow_empty=True
    )
    normalized["rebuild_cmds"] = _required_string_list(row["rebuild_cmds"], "rebuild_cmds")
    normalized["test_cmds"] = _required_string_list(row["test_cmds"], "test_cmds")
    normalized["print_cmds"] = _required_string_list(row["print_cmds"], "print_cmds")
    patch = row["patch"]
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError(f"row {line_number} patch must be a non-empty string")
    # Patches are byte-sensitive: do not strip trailing blank/context lines.
    normalized["patch"] = patch
    test_patch = row["test_patch"]
    if test_patch is None:
        normalized["test_patch"] = ""
    elif isinstance(test_patch, str):
        normalized["test_patch"] = test_patch
    else:
        raise ValueError(f"row {line_number} test_patch must be a string or null")
    if not isinstance(row["metadata"], dict):
        raise ValueError(f"row {line_number} metadata must be an object")
    normalized["metadata"] = dict(row["metadata"])
    normalized["difficulty"] = _required_string(row["difficulty"], "difficulty")
    _validate_log_parser(row["log_parser"])
    normalized["log_parser"] = row["log_parser"]
    normalized["schema"] = SCHEMA
    return normalized


def load_rows(path: Path, *, expected_count: int | None = None) -> list[dict[str, Any]]:
    """Load and validate an OS-Bench JSONL file."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"OS-Bench dataset does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
        rows.append(normalize_row(value, line_number=line_number))
    if not rows:
        raise ValueError(f"OS-Bench dataset contains no tasks: {path}")
    identifiers = [row["instance_id"] for row in rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("OS-Bench dataset contains duplicate instance_id values")
    if expected_count is not None and len(rows) != expected_count:
        raise ValueError(
            f"expected {expected_count} OS-Bench tasks, found {len(rows)} in {path}"
        )
    return rows


def select_rows(
    rows: Iterable[dict[str, Any]], task_ids: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    requested = list(dict.fromkeys(task_ids or []))
    by_id = {row["instance_id"]: row for row in rows}
    if not requested:
        return list(rows)
    missing = [task_id for task_id in requested if task_id not in by_id]
    if missing:
        raise ValueError(f"unknown OS-Bench task IDs: {missing}")
    return [by_id[task_id] for task_id in requested]


def docker_image_id(image: str) -> str | None:
    result = _run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        check=False,
        timeout=60,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def resolve_images(
    row: dict[str, Any], *, image_prefix: str | None = "component-method/osbench-cpp"
) -> dict[str, Any]:
    """Resolve the prepared runtime image, falling back to the dataset image."""
    official = row["docker_image"]
    prepared = f"{image_prefix}:{row['instance_id']}" if image_prefix else None
    official_id = docker_image_id(official)
    prepared_id = docker_image_id(prepared) if prepared else None
    runtime = prepared if prepared_id else official
    runtime_id = prepared_id or official_id
    if not runtime_id:
        raise RuntimeError(
            f"no Docker image available for {row['instance_id']}: "
            f"prepared={prepared!r} official={official!r}"
        )
    return {
        "official_image": official,
        "official_image_id": official_id,
        "prepared_image": prepared,
        "prepared_image_id": prepared_id,
        "runtime_image": runtime,
        "runtime_image_id": runtime_id,
        "runtime_image_source": "prepared" if prepared_id else "dataset",
    }


def materialize_source(
    image: str,
    destination: Path,
    *,
    refresh: bool = False,
    container_repository: str = CONTAINER_REPOSITORY,
) -> Path:
    """Copy a task repository out of its Docker image into a host snapshot."""
    destination = destination.expanduser().resolve()
    if destination.is_dir() and any(destination.iterdir()) and not refresh:
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    container = _run(["docker", "create", image, "sleep", "90"], timeout=120).stdout.strip()
    if not container:
        raise RuntimeError(f"docker create returned no container for {image}")
    try:
        _run(["docker", "cp", f"{container}:{container_repository}", str(destination)], timeout=900)
    finally:
        _run(["docker", "rm", "-f", container], check=False, timeout=120)
    if not destination.is_dir():
        raise RuntimeError(f"source snapshot was not created: {destination}")
    git_directory = destination / ".git"
    if git_directory.exists():
        shutil.rmtree(git_directory)
    return destination


def _configure_command(rebuild_cmds: list[str]) -> str | None:
    for command in rebuild_cmds:
        for segment in re.split(r"\s*(?:;|&&)\s*", command):
            if not segment.strip():
                continue
            if "cmake" not in segment or "--build" in segment:
                continue
            if "-S" not in segment and "--source" not in segment:
                continue
            if "CMAKE_EXPORT_COMPILE_COMMANDS" not in segment:
                segment = segment.rstrip() + " -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
            return segment.strip()
    return None


def _container_relative(value: str, directory: Path, container_root: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value
    resolved = path.resolve()
    try:
        resolved.relative_to(container_root)
    except ValueError:
        return value
    return os.path.relpath(resolved, directory)


def _normalize_arguments(
    arguments: list[str], directory: Path, container_root: Path
) -> list[str]:
    """Keep the flags the C++ backend consumes and make their paths portable."""
    path_flags = {"-I", "-isystem", "-iquote", "-include"}
    result: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in path_flags:
            if index + 1 >= len(arguments):
                result.append(argument)
                index += 1
                continue
            value = _container_relative(arguments[index + 1], directory, container_root)
            result.extend((argument, value))
            index += 2
            continue
        if argument.startswith("-I") and len(argument) > 2:
            value = _container_relative(argument[2:], directory, container_root)
            result.append("-I" + value)
            index += 1
            continue
        if argument.startswith(("-D", "-U", "-std=", "--target=")):
            result.append(argument)
        index += 1
    return result


def normalize_compile_commands(
    payload: Any,
    snapshot_root: Path,
    *,
    container_root: Path = Path(CONTAINER_REPOSITORY),
) -> list[dict[str, Any]]:
    """Convert container-absolute compile commands to snapshot-relative entries."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("compile_commands.json must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ValueError(f"compile_commands[{index}] is not an object")
        directory_value = entry.get("directory")
        file_value = entry.get("file")
        if not isinstance(directory_value, str) or not isinstance(file_value, str):
            raise ValueError(f"compile_commands[{index}] needs directory and file")
        directory = Path(directory_value)
        if not directory.is_absolute():
            directory = container_root / directory
        directory = directory.resolve()
        source = Path(file_value)
        if not source.is_absolute():
            source = directory / source
        source = source.resolve()
        try:
            directory.relative_to(container_root)
            source.relative_to(container_root)
        except ValueError as exc:
            raise ValueError(
                f"compile_commands[{index}] escapes {container_root}: "
                f"directory={directory} file={source}"
            ) from exc
        directory_relative = os.path.relpath(directory, container_root)
        source_relative = os.path.relpath(source, directory)
        raw_arguments = entry.get("arguments")
        if raw_arguments is None:
            command = entry.get("command")
            if not isinstance(command, str):
                raise ValueError(
                    f"compile_commands[{index}] needs arguments or a command string"
                )
            raw_arguments = shlex.split(command)
        if not isinstance(raw_arguments, list) or not all(
            isinstance(value, str) for value in raw_arguments
        ):
            raise ValueError(f"compile_commands[{index}].arguments must be a string list")
        arguments = _normalize_arguments(raw_arguments, directory, container_root)
        key = (directory_relative, source_relative, tuple(arguments))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "directory": directory_relative,
                "file": source_relative,
                "arguments": arguments,
            }
        )
    if not normalized:
        raise ValueError("compile_commands.json contains no usable entries")
    return normalized


def _copy_compile_commands_from_image(
    image: str,
    destination: Path,
    *,
    container_repository: str = CONTAINER_REPOSITORY,
) -> Path | None:
    container = _run(["docker", "create", image, "sleep", "30"], timeout=120).stdout.strip()
    if not container:
        return None
    try:
        temporary = destination.parent / (destination.name + ".container")
        _run(
            [
                "docker",
                "cp",
                f"{container}:{container_repository}/build/compile_commands.json",
                str(temporary),
            ],
            check=False,
            timeout=300,
        )
        if temporary.is_file():
            temporary.replace(destination)
            return destination
        return None
    finally:
        _run(["docker", "rm", "-f", container], check=False, timeout=60)


def _generate_compile_commands(
    image: str,
    row: dict[str, Any],
    destination: Path,
    *,
    container_repository: str = CONTAINER_REPOSITORY,
) -> Path | None:
    command = _configure_command(row["rebuild_cmds"])
    if not command:
        return None
    container = _run(["docker", "create", image, "sleep", "600"], timeout=120).stdout.strip()
    if not container:
        return None
    try:
        _run(["docker", "start", container], timeout=120)
        _run(
            [
                "docker",
                "exec",
                "-w",
                container_repository,
                container,
                "/bin/bash",
                "-lc",
                command,
            ],
            timeout=1800,
        )
        temporary = destination.parent / (destination.name + ".container")
        _run(
            [
                "docker",
                "cp",
                f"{container}:{container_repository}/build/compile_commands.json",
                str(temporary),
            ],
            check=False,
            timeout=300,
        )
        if temporary.is_file():
            temporary.replace(destination)
            return destination
        return None
    finally:
        _run(["docker", "rm", "-f", container], check=False, timeout=120)


def collect_compile_commands(
    snapshot: Path,
    row: dict[str, Any],
    image: str,
    *,
    mode: str = "auto",
    container_repository: str = CONTAINER_REPOSITORY,
) -> dict[str, Any]:
    """Create ``compile_commands.json`` at the snapshot root when possible."""
    if mode not in {"auto", "off", "configure"}:
        raise ValueError("compile_commands mode must be auto, off, or configure")
    snapshot = snapshot.resolve()
    destination = snapshot / "compile_commands.json"
    sidecar = snapshot / "compile_commands.provenance.json"
    if destination.is_file() and sidecar.is_file():
        previous = _read_json(sidecar)
        if previous.get("sha256") == _sha256_file(destination):
            return previous
    if destination.is_file():
        # The root file is either an unprovenanced raw copy or a stale
        # normalization. Regenerate it instead of normalizing it twice.
        destination.unlink()
    source = "missing"
    warning = None
    candidate = snapshot / "build" / "compile_commands.json"
    if candidate.is_file():
        candidate.replace(destination)
        source = "snapshot-build"
    elif mode != "off":
        extracted = _copy_compile_commands_from_image(
            image,
            destination,
            container_repository=container_repository,
        )
        if extracted is not None:
            source = "image-build"
        elif mode in {"auto", "configure"}:
            generated = _generate_compile_commands(
                image,
                row,
                destination,
                container_repository=container_repository,
            )
            if generated is not None:
                source = "image-configure"
            elif mode == "configure":
                warning = "cmake configure did not produce compile_commands.json"
    info: dict[str, Any] = {
        "status": "missing",
        "source": source,
        "path": "compile_commands.json",
        "command_count": 0,
        "sha256": None,
    }
    if not destination.is_file():
        if warning:
            info["warning"] = warning
        return info
    try:
        payload = _read_json(destination)
        normalized = normalize_compile_commands(
            payload,
            snapshot,
            container_root=Path(container_repository),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if warning is None:
            warning = f"compile_commands.json could not be normalized: {exc}"
        info["warning"] = warning
        return info
    _write_json(destination, normalized)
    info.update(
        status="ok",
        command_count=len(normalized),
        sha256=_sha256_file(destination),
    )
    if warning:
        info["warning"] = warning
    _write_json(sidecar, info)
    return info

def prune_source_snapshot(snapshot: Path) -> None:
    """Drop build products and generated directories from a host snapshot."""
    snapshot = snapshot.resolve()
    for name in PRUNE_DIRECTORIES:
        path = snapshot / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
    for path in snapshot.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(snapshot).parts
        if any(part in PRUNE_DIRECTORIES for part in relative_parts):
            continue
        if path.name in PRUNE_FILES or path.name.endswith((".o", ".a", ".so", ".pyc")):
            path.unlink()


def source_stats(snapshot: Path) -> dict[str, Any]:
    snapshot = snapshot.resolve()
    by_suffix: dict[str, int] = {}
    source_files = 0
    source_bytes = 0
    total_files = 0
    total_bytes = 0
    for path in snapshot.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        total_files += 1
        total_bytes += size
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative_parts = path.relative_to(snapshot).parts
        if any(part in SCAN_EXCLUDED_DIRECTORIES for part in relative_parts):
            continue
        source_files += 1
        source_bytes += size
        by_suffix[path.suffix.lower()] = by_suffix.get(path.suffix.lower(), 0) + 1
    return {
        "source_files": source_files,
        "source_bytes": source_bytes,
        "source_by_suffix": dict(sorted(by_suffix.items())),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "top_level": sorted(
            path.name for path in snapshot.iterdir() if path.is_dir() or path.is_file()
        ),
    }


def _cpp_standard(row: dict[str, Any]) -> str:
    text = " ".join(row.get("rebuild_cmds", []))
    match = re.search(r"CMAKE_CXX_STANDARD[=:\s]+(\d+)", text)
    if match:
        value = match.group(1)
        if value in {"11", "14", "17", "20", "23"}:
            return f"c++{value}"
    return "c++17"


def task_languages(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "cpp",
            "standard": _cpp_standard(row),
            "compilation_database": "compile_commands.json",
        }
    ]


def write_task_package(
    row: dict[str, Any],
    snapshot: Path,
    compile_info: dict[str, Any],
    images: dict[str, Any],
    destination: Path,
    *,
    dataset_path: Path,
) -> dict[str, Any]:
    """Write one OS-Bench offline task package."""
    destination = destination.expanduser().resolve()
    snapshot = snapshot.resolve()
    evaluation_root = destination / "evaluation_only"
    evaluation_root.mkdir(parents=True, exist_ok=True)
    parser_path = evaluation_root / "osbench_log_parser.py"
    parser_path.write_text(row["log_parser"].rstrip() + "\n", encoding="utf-8")
    public = {
        "schema": PUBLIC_TASK_SCHEMA,
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "language": row["language"],
        "image_name": images["runtime_image"],
        "official_image_name": images["official_image"],
        "problem_statement": row["problem_statement"],
        "interface": "",
        "FAIL_TO_PASS": row["FAIL_TO_PASS"],
        "PASS_TO_PASS": row["PASS_TO_PASS"],
        "difficulty": row["difficulty"],
        "migration_direction": row["migration_direction"],
        "metadata": row["metadata"],
        "source_subdir": ".",
        "compile_commands": "compile_commands.json"
        if compile_info.get("status") == "ok"
        else None,
        "task_type": "cross_platform_migration",
    }
    private = {
        "schema": PRIVATE_TASK_SCHEMA,
        "warning": "仅供评测使用，不得提供给任务 Agent。",
        "reference_patch": row["patch"],
        "test_patch": row["test_patch"],
        "install_config": {
            "test_cmd": row["test_cmds"],
            "rebuild_cmd": row["rebuild_cmds"],
            "print_cmd": row["print_cmds"],
            "log_parser": "osbench_inline",
            "log_parser_source": row["log_parser"],
            "log_parser_path": "evaluation_only/osbench_log_parser.py",
        },
        "evaluation_adjustments": {},
        "osbench": {
            "migration_direction": row["migration_direction"],
            "difficulty": row["difficulty"],
            "metadata": row["metadata"],
        },
    }
    stats = source_stats(snapshot)
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "source_dataset": str(dataset_path.resolve()),
        "source_dataset_sha256": _sha256_file(dataset_path),
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "source_commit": row["base_commit"],
        "source_subdir": ".",
        "source_snapshot": "source_snapshot",
        "component_count": 0,
        "images": images,
        "compile_commands": compile_info,
        "source_stats": stats,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(destination / "task.json", public)
    _write_json(evaluation_root / "task_private.json", private)
    _write_json(destination / "provenance.json", provenance)
    return {
        "public": public,
        "private": private,
        "provenance": provenance,
    }


def _ensure_symlink(link: Path, target: Path) -> None:
    target = target.resolve()
    if link.is_symlink():
        if link.resolve() != target:
            raise RuntimeError(f"existing symlink points elsewhere: {link}")
        return
    if link.exists():
        raise RuntimeError(f"existing path is not a symlink: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


def workspace_config(
    method: dict[str, Any],
    api_base: str,
    *,
    languages: list[dict[str, Any]],
    dataset_path: Path,
    task_count: int,
) -> dict[str, Any]:
    return {
        "schema": WORKSPACE_SCHEMA,
        "experiment_id": "component-method-osbench-windows2linux-cpp",
        "frozen_pipeline": "component_method.workflow",
        "model": method["task_model"],
        "api_base": api_base.rstrip("/"),
        "embedding": method["embedding"],
        "pipeline": method["pipeline"],
        "languages": languages,
        "candidate_config": "repository/config/reference/candidate_generation.json",
        "bootstrap_embeddings": "offline_artifacts/embeddings",
        "dataset": {
            "path": str(dataset_path.resolve()),
            "sha256": _sha256_file(dataset_path),
            "task_count": task_count,
            "source": "OS-Bench windows2linux C++ split",
        },
    }


def task_config(
    row: dict[str, Any],
    *,
    method: dict[str, Any],
    api_base: str,
    snapshot: Path,
    candidate_path: Path,
    candidate_sha256: str,
    workspace: Path,
    runtime_image: str,
) -> dict[str, Any]:
    pipeline = method["pipeline"]
    return {
        "schema": TASK_SCHEMA,
        "languages": task_languages(row),
        "task_id": row["instance_id"],
        "repository": row["repo"],
        "source_commit": row["base_commit"],
        "model": method["task_model"],
        "api_base": api_base.rstrip("/"),
        "agent_timeout_seconds": pipeline["agent_timeout_seconds"],
        "extraction_workers": pipeline["extraction_workers"],
        "review_workers": pipeline["review_workers"],
        "runtime_image": runtime_image,
        "candidate_file": str(candidate_path),
        "candidate_sha256": candidate_sha256,
        "repository_root": str(snapshot.resolve()),
        "baseline_experiment": "repository/src/component_method/task_execution/config",
        "focus_context_instructions": "repository/config/prompts/focus_context_instructions.txt",
        "protocol_contract_instructions": "repository/config/prompts/protocol_contract_instructions.txt",
        "protocol_contract_schema": "repository/config/schemas/protocol_contract_schema.json",
        "packet_config": pipeline["packet_config"],
        "max_review_repair_rounds": pipeline["max_review_repair_rounds"],
        "retrieval_attempt": "retrieval_01",
        "task_attempt": "task_01",
        "source_subdir": ".",
        "apply_review_revisions_without_rereview": False,
        "osbench": {
            "migration_direction": row["migration_direction"],
            "difficulty": row["difficulty"],
            "workspace": str(workspace.resolve()),
        },
    }


def task_record(
    row: dict[str, Any],
    *,
    index: int,
    snapshot: Path,
    images: dict[str, Any],
    candidate_path: Path,
) -> dict[str, Any]:
    return {
        "index": index,
        "instance_id": row["instance_id"],
        "cohort": "primary",
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "source_path": "",
        "source_subdir": ".",
        "runtime_image": images["runtime_image"],
        "repository_root": str(snapshot.resolve()),
        "direct_status": "pending",
        "component_status": "pending",
        "imported_component_source": None,
        "frozen_candidate": str(candidate_path),
        "languages": task_languages(row),
        "osbench": {
            "migration_direction": row["migration_direction"],
            "difficulty": row["difficulty"],
            "task_type": "cross_platform_migration",
        },
    }


def prepare_osbench(
    dataset_path: Path,
    workspace: Path,
    project_root: Path,
    *,
    image_prefix: str | None = "component-method/osbench-cpp",
    task_ids: Iterable[str] | None = None,
    expected_count: int | None = 6,
    extract_sources: bool = True,
    compile_commands_mode: str = "auto",
    api_base: str = "",
    refresh: bool = False,
) -> dict[str, Any]:
    """Prepare OS-Bench tasks and return a machine-readable summary."""
    dataset_path = dataset_path.expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    rows = select_rows(load_rows(dataset_path), task_ids)
    if expected_count is not None and len(rows) != expected_count:
        raise ValueError(
            f"expected {expected_count} selected OS-Bench tasks, found {len(rows)}"
        )
    if not rows:
        raise ValueError("no OS-Bench tasks selected")
    workspace.mkdir(parents=True, exist_ok=True)
    _ensure_symlink(workspace / "repository", project_root)
    offline_tasks = workspace / "offline_artifacts" / "tasks"
    runtime_tasks = workspace / "tasks"
    offline_tasks.mkdir(parents=True, exist_ok=True)
    runtime_tasks.mkdir(parents=True, exist_ok=True)
    method = _read_json(project_root / "config" / "method.json")

    prepared: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        task_id = row["instance_id"]
        offline_task = offline_tasks / task_id
        runtime_task = runtime_tasks / task_id
        snapshot = offline_task / "source_snapshot"
        if refresh:
            for path in (offline_task, runtime_task):
                if path.exists():
                    shutil.rmtree(path)
        offline_task.mkdir(parents=True, exist_ok=True)
        runtime_task.mkdir(parents=True, exist_ok=True)
        images = resolve_images(row, image_prefix=image_prefix)
        if extract_sources:
            materialize_source(
                images["runtime_image"],
                snapshot,
                refresh=refresh,
            )
        elif not snapshot.is_dir():
            raise FileNotFoundError(
                f"source snapshot is missing and --no-materialize-sources was used: {snapshot}"
            )
        compile_info = collect_compile_commands(
            snapshot,
            row,
            images["runtime_image"],
            mode=compile_commands_mode,
        )
        prune_source_snapshot(snapshot)
        for directory in IMAGE_VOLUME_DIRECTORIES:
            (snapshot / directory).mkdir(exist_ok=True)
        write_task_package(
            row,
            snapshot,
            compile_info,
            images,
            offline_task,
            dataset_path=dataset_path,
        )
        candidate_path = runtime_task / "candidates" / "protocol_candidates_v2.json"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_sha256 = _sha256_file(candidate_path) if candidate_path.is_file() else ""
        template = task_config(
            row,
            method=method,
            api_base=api_base,
            snapshot=snapshot,
            candidate_path=candidate_path,
            candidate_sha256=candidate_sha256,
            workspace=workspace,
            runtime_image=images["runtime_image"],
        )
        _write_json(runtime_task / "pipeline_config.template.json", template)
        _write_json(runtime_task / "config.json", template)
        record = task_record(
            row,
            index=index,
            snapshot=snapshot,
            images=images,
            candidate_path=candidate_path,
        )
        _write_json(runtime_task / "task_record.json", record)
        records.append(record)
        prepared.append(
            {
                "instance_id": task_id,
                "repo": row["repo"],
                "runtime_image": images["runtime_image"],
                "runtime_image_id": images["runtime_image_id"],
                "official_image": images["official_image"],
                "source_snapshot": str(snapshot),
                "compile_commands": compile_info,
                "source_stats": source_stats(snapshot),
                "offline_task": str(offline_task),
                "runtime_task": str(runtime_task),
            }
        )

    languages = task_languages(rows[0])
    config = workspace_config(
        method,
        api_base,
        languages=languages,
        dataset_path=dataset_path,
        task_count=len(rows),
    )
    _write_json(workspace / "config.json", config)
    _write_json(
        workspace / "tasks.json",
        {
            "schema": "component-method-task-list-v1",
            "tasks": records,
        },
    )
    summary = {
        "schema": PREPARATION_SCHEMA,
        "dataset": str(dataset_path),
        "dataset_sha256": _sha256_file(dataset_path),
        "workspace": str(workspace),
        "release_root": str(workspace),
        "task_count": len(prepared),
        "tasks": prepared,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(workspace / "preparation_manifest.json", summary)
    return summary


def preflight_workspace(
    workspace: Path,
    *,
    task_ids: Iterable[str] | None = None,
    require_model_env: bool = False,
    run_scan: bool = False,
    scan_limit: int = 20,
) -> dict[str, Any]:
    """Check a prepared OS-Bench workspace without running model stages."""
    workspace = workspace.expanduser().resolve()
    failures: list[str] = []
    warnings: list[str] = []
    tasks_path = workspace / "tasks.json"
    config_path = workspace / "config.json"
    if not tasks_path.is_file() or not config_path.is_file():
        raise FileNotFoundError(
            f"not a prepared OS-Bench workspace: {workspace} "
            f"(expected tasks.json and config.json)"
        )
    import importlib.util

    for package in ("docker", "clang", "filelock", "numpy", "scipy", "yaml"):
        if importlib.util.find_spec(package) is None:
            failures.append(f"missing Python package: {package}")
    try:
        importlib.metadata.version("libclang")
    except importlib.metadata.PackageNotFoundError:
        failures.append("missing Python package: libclang")
    try:
        _run(["docker", "info"], timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        failures.append(f"Docker is unavailable: {exc}")
    if require_model_env:
        for name in ("OPENAI_API_KEY", "OPENAI_API_BASE"):
            if not os.environ.get(name):
                failures.append(f"missing environment variable: {name}")
    repository_link = workspace / "repository"
    if not repository_link.is_dir():
        failures.append(f"workspace repository link is missing: {repository_link}")
    tasks_payload = _read_json(tasks_path)
    rows = tasks_payload.get("tasks", [])
    if not isinstance(rows, list) or not rows:
        failures.append("tasks.json contains no tasks")
        rows = []
    selected = list(dict.fromkeys(task_ids or []))
    if selected:
        by_id = {row.get("instance_id"): row for row in rows}
        missing = [task_id for task_id in selected if task_id not in by_id]
        if missing:
            failures.append(f"unknown task IDs: {missing}")
        rows = [by_id[task_id] for task_id in selected if task_id in by_id]

    task_reports: list[dict[str, Any]] = []
    for row in rows:
        task_id = row.get("instance_id")
        report: dict[str, Any] = {"instance_id": task_id, "ok": True, "checks": {}}
        offline_task = workspace / "offline_artifacts" / "tasks" / task_id
        snapshot = offline_task / "source_snapshot"
        public_path = offline_task / "task.json"
        private_path = offline_task / "evaluation_only" / "task_private.json"
        provenance_path = offline_task / "provenance.json"
        for path in (public_path, private_path, provenance_path, snapshot):
            if not path.exists():
                report["ok"] = False
                failures.append(f"{task_id}: missing {path}")
        if not report["ok"]:
            task_reports.append(report)
            continue
        public = _read_json(public_path)
        private = _read_json(private_path)
        provenance = _read_json(provenance_path)
        image = public.get("image_name") or row.get("runtime_image")
        if not image:
            report["ok"] = False
            failures.append(f"{task_id}: no runtime image")
        else:
            image_id = docker_image_id(image)
            report["checks"]["image"] = image
            report["checks"]["image_id"] = image_id
            if not image_id:
                report["ok"] = False
                failures.append(f"{task_id}: Docker image is missing: {image}")
            else:
                probe = _run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network=none",
                        "--entrypoint",
                        "/bin/bash",
                        image,
                        "-lc",
                        "git -C /testbed rev-parse HEAD; "
                        "command -v g++ || true; "
                        "command -v nm || true; "
                        "command -v cmake || true; "
                        "command -v python || true",
                    ],
                    check=False,
                    timeout=120,
                )
                lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
                if probe.returncode:
                    report["ok"] = False
                    failures.append(f"{task_id}: image probe failed: {probe.stderr[-1000:]}")
                elif not lines or lines[0] != public.get("base_commit"):
                    report["ok"] = False
                    failures.append(
                        f"{task_id}: image HEAD {lines[0] if lines else '?'} "
                        f"does not match {public.get('base_commit')}"
                    )
                else:
                    report["checks"]["base_commit"] = lines[0]
                    tools = {
                        name: any(Path(value).name == name for value in lines[1:])
                        for name in ("g++", "nm", "cmake", "python")
                    }
                    report["checks"]["tools"] = tools
                    if not tools["g++"] or not tools["nm"]:
                        report["ok"] = False
                        failures.append(f"{task_id}: image lacks g++ or nm")
                    if not tools["python"]:
                        warnings.append(
                            f"{task_id}: image lacks `python`; the DSH patch checker requires it"
                        )
        compile_path = snapshot / "compile_commands.json"
        if not compile_path.is_file():
            warnings.append(f"{task_id}: compile_commands.json is missing")
        else:
            try:
                payload = _read_json(compile_path)
                normalized = normalize_compile_commands(payload, snapshot)
                report["checks"]["compile_commands"] = len(normalized)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                report["ok"] = False
                failures.append(f"{task_id}: invalid compile_commands.json: {exc}")
        install = private.get("install_config", {})
        for field in ("rebuild_cmd", "test_cmd", "print_cmd"):
            value = install.get(field)
            if not isinstance(value, list) or not value:
                report["ok"] = False
                failures.append(f"{task_id}: install_config.{field} is missing")
        parser_source = install.get("log_parser_source")
        try:
            _validate_log_parser(parser_source)
        except ValueError as exc:
            report["ok"] = False
            failures.append(f"{task_id}: {exc}")
        stats = source_stats(snapshot)
        report["checks"]["source_stats"] = stats
        if stats["source_files"] == 0:
            report["ok"] = False
            failures.append(f"{task_id}: no scannable C/C++ source files")
        if run_scan:
            try:
                from component_method.source_scan.scanning import source_files, task_backends

                task_config_path = workspace / "tasks" / task_id / "config.json"
                config = _read_json(task_config_path)
                selection = task_backends(config)
                stream = source_files(snapshot, ".", selection)
                if scan_limit > 0:
                    files = list(itertools.islice(stream, scan_limit))
                else:
                    files = list(stream)
                units = sum(
                    len(backend.extract_units(entry["file_id"], entry["source_code"]))
                    for entry, backend in files
                )
                report["checks"]["scan"] = {
                    "files": len(files),
                    "units": units,
                    "limited_to": scan_limit,
                }
            except Exception as exc:  # pragma: no cover - environment dependent
                report["ok"] = False
                failures.append(f"{task_id}: C++ source scan failed: {exc}")
        task_reports.append(report)
        if not report["ok"]:
            failures.append(f"{task_id}: preflight failed")
    return {
        "schema": "osbench-preflight-v1",
        "workspace": str(workspace),
        "ok": not failures,
        "failures": failures,
        "warnings": warnings,
        "tasks": task_reports,
    }