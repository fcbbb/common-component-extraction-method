#!/usr/bin/env python3
"""Freeze migration workspace regions as focus/context extraction packets.

The OS-Bench/FFSIM pipeline starts from a frozen candidate file produced by the
task-blind signal stages.  Migration tasks already have exactly one source
workspace per attempt, so this adapter partitions that workspace directly:

* every eligible source file is parsed with the language backend selected in
  ``config.json`` (``cpp`` for IPP/Kylin, ``python`` for MUSA);
* parsed units become exact focus members, which lets the normal extraction
  prompt and the protocol-contract gate use real source identities;
* files are packed into deterministic regions ordered by path.

The result has the same packet shape as ``prepare_inputs.py``, so the rest of
the pipeline (extract/curate/publish/retrieval) is unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json, write_json

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".components",
    ".venv",
    "__pycache__",
    "build",
    "build-release",
    "cmake-build-debug",
    "component_bundle",
    "dist",
    "evaluator",
    "gold",
    "gold_authored",
    "generated",
    "node_modules",
    "test",
    "tests",
    "third_party",
    "upstream_nonconforming",
    "vendor",
    "venv",
}
DEFAULT_EXCLUDED_FILENAMES = ["test_*.py", "*_test.py"]
DEFAULT_MAX_FILE_BYTES = 1024 * 1024


def _backend(language: str):
    from component_method.languages.registry import default_registry

    return default_registry().resolve({"language": language}).single()


def _source_files(
    workspace: Path,
    *,
    extensions: set[str],
    excluded_dirs: set[str],
    excluded_filenames: list[str],
    max_file_bytes: int,
) -> tuple[list[Path], list[dict[str, str]]]:
    files: list[Path] = []
    gaps: list[dict[str, str]] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink():
            gaps.append({"file_id": path.relative_to(workspace).as_posix(), "reason": "symlink"})
            continue
        if not path.is_file() or path.suffix not in extensions:
            continue
        relative = path.relative_to(workspace)
        if any(part in excluded_dirs for part in relative.parts[:-1]):
            continue
        if any(path.match(pattern) for pattern in excluded_filenames):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                gaps.append({"file_id": relative.as_posix(), "reason": "file too large"})
                continue
        except OSError as exc:
            gaps.append({"file_id": relative.as_posix(), "reason": f"stat failed: {exc}"})
            continue
        files.append(path)
    return files, gaps


def _workspace_digest(files: list[Path], workspace: Path) -> tuple[str, list[str]]:
    """Hash every eligible source file, not only the ones that parsed.

    The digest is stored in the frozen packet input.  Extraction recomputes it
    before starting so an outer agent cannot edit the workspace between
    ``source_scan`` and ``extract`` without being detected.
    """
    digest = hashlib.sha256()
    relative_files: list[str] = []
    for path in sorted(files):
        relative = path.relative_to(workspace).as_posix()
        relative_files.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError as exc:
            raise RuntimeError(f"cannot fingerprint source file {relative}: {exc}") from exc
    return digest.hexdigest(), relative_files


def _workspace_from_config(config: dict[str, Any]) -> Path:
    workspace = Path(str(config.get("repository_root") or "")).expanduser()
    if not workspace.is_absolute():
        workspace = (PROJECT / workspace).resolve()
    else:
        workspace = workspace.resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"migration workspace is missing: {workspace}")
    return workspace


def _packet_scan_options(
    config: dict[str, Any],
    backend: Any,
) -> tuple[set[str], set[str], list[str], int]:
    packet_config = dict(config.get("packet_config") or {})
    extensions = {
        str(item).lower()
        for item in packet_config.get(
            "extensions", backend.scan_policy().get("extensions", [])
        )
    }
    excluded_dirs = set(
        packet_config.get("excluded_directory_names") or DEFAULT_EXCLUDED_DIRS
    )
    excluded_filenames = list(
        packet_config.get("excluded_filenames") or DEFAULT_EXCLUDED_FILENAMES
    )
    max_file_bytes = int(
        packet_config.get("max_file_bytes") or DEFAULT_MAX_FILE_BYTES
    )
    return extensions, excluded_dirs, excluded_filenames, max_file_bytes


def verify_workspace_unchanged(
    config: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Refuse extraction when the source tree changed after source_scan."""
    expected = payload.get("workspace_sha256")
    if not expected:
        return
    migration = config.get("migration") or {}
    scenario = str(migration.get("scenario") or config.get("scenario") or "")
    language = str(
        config.get("language") or ("python" if scenario == "cuda_to_musa" else "cpp")
    )
    backend = _backend(language)
    workspace = _workspace_from_config(config)
    extensions, excluded_dirs, excluded_filenames, max_file_bytes = _packet_scan_options(
        config, backend
    )
    files, _ = _source_files(
        workspace,
        extensions=extensions,
        excluded_dirs=excluded_dirs,
        excluded_filenames=excluded_filenames,
        max_file_bytes=max_file_bytes,
    )
    actual, actual_files = _workspace_digest(files, workspace)
    if actual == expected and actual_files == list(payload.get("workspace_files") or []):
        return
    expected_files = list(payload.get("workspace_files") or [])
    missing = sorted(set(expected_files) - set(actual_files))
    added = sorted(set(actual_files) - set(expected_files))
    detail = []
    if missing:
        detail.append(f"missing={missing[:10]}")
    if added:
        detail.append(f"added={added[:10]}")
    if not detail:
        detail.append("content changed")
    raise RuntimeError(
        "migration workspace changed after source_scan; "
        "do not edit task code before extraction finishes "
        f"({'; '.join(detail)})"
    )


def _units_for(
    backend: Any,
    file_id: str,
    source: str,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        units = backend.extract_units(file_id, source)
    except Exception as exc:  # noqa: BLE001 - a bad file must not hide the corpus
        return [], f"{type(exc).__name__}: {exc}"
    prepared = []
    for unit in units:
        prepared.append(
            {
                "file_id": file_id,
                "unit_id": unit.unit_key,
                "unit_key": unit.unit_key,
                "kind": unit.kind,
                "qualified_name": unit.qualified_name,
                "signature": unit.signature,
                "language": unit.language,
                "backend_id": unit.backend_id,
                "line_start": unit.span.start_line,
                "line_end": unit.span.end_line,
            }
        )
    return prepared, None


def _packets(
    files: list[tuple[str, list[dict[str, Any]], int]],
    *,
    max_files: int,
    max_units: int,
) -> list[dict[str, Any]]:
    groups: list[list[tuple[str, list[dict[str, Any]], int]]] = []
    current: list[tuple[str, list[dict[str, Any]], int]] = []
    current_units = 0
    for item in files:
        unit_count = len(item[1])
        if current and (
            len(current) >= max_files
            or (max_units and current_units + unit_count > max_units)
        ):
            groups.append(current)
            current = []
            current_units = 0
        current.append(item)
        current_units += unit_count
        if max_units and current_units >= max_units:
            groups.append(current)
            current = []
            current_units = 0
    if current:
        groups.append(current)

    packets = []
    for index, group in enumerate(groups, 1):
        packet_id = f"region_{index:03d}"
        candidate_id = f"region-{index:03d}"
        focus_units = [unit for _, units, _ in group for unit in units]
        visible_files = [file_id for file_id, _, _ in group]
        packets.append(
            {
                "packet_id": packet_id,
                "candidate_ids": [candidate_id],
                "candidate_ranks": [1],
                "focus_groups": [
                    {
                        "candidate_id": candidate_id,
                        "candidate_rank": 1,
                        "focus_units": focus_units,
                        "seed_evidence": [
                            {
                                "file_id": file_id,
                                "line_start": 1,
                                "line_end": max(1, line_count),
                            }
                            for file_id, _, line_count in group
                        ],
                        "candidate_unit_count": len(focus_units),
                        "expanded_unit_count": 0,
                    }
                ],
                "focus_units": focus_units,
                "context_units": [],
                "focus_files": visible_files,
                "context_files": [],
                "visible_files": visible_files,
                "visible_unit_count": len(focus_units),
                "focus_unit_count": len(focus_units),
                "context_unit_count": 0,
            }
        )
    return packets


def build_inputs(config: dict[str, Any], *, task_root: Path | None = None) -> dict[str, Any]:
    """Build ``inputs/focus_context_packets.json`` for one migration task."""
    task_root = (task_root or ROOT).resolve()
    migration = config.get("migration") or {}
    scenario = str(migration.get("scenario") or config.get("scenario") or "")
    language = str(config.get("language") or ("python" if scenario == "cuda_to_musa" else "cpp"))
    backend = _backend(language)
    backend_id = str(config.get("backend_id") or backend.backend_id)
    if not backend_id.startswith(f"{language}@"):
        raise RuntimeError(f"backend identity does not match {language}: {backend_id}")

    workspace = _workspace_from_config(config)
    if hasattr(backend, "set_repository"):
        backend.set_repository(workspace)

    packet_config = dict(config.get("packet_config") or {})
    extensions, excluded_dirs, excluded_filenames, max_file_bytes = _packet_scan_options(
        config, backend
    )
    max_files = int(packet_config.get("max_files_per_packet") or 8)
    max_units = int(packet_config.get("max_units_per_packet") or 200)
    if max_files < 1 or max_units < 1:
        raise RuntimeError("packet_config limits must be positive")

    files, gaps = _source_files(
        workspace,
        extensions=extensions,
        excluded_dirs=excluded_dirs,
        excluded_filenames=excluded_filenames,
        max_file_bytes=max_file_bytes,
    )
    workspace_sha256, workspace_files = _workspace_digest(files, workspace)
    parsed: list[tuple[str, list[dict[str, Any]], int]] = []
    for path in files:
        file_id = path.relative_to(workspace).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            gaps.append({"file_id": file_id, "reason": f"unreadable: {exc}"})
            continue
        units, error = _units_for(backend, file_id, source)
        if error is not None:
            gaps.append({"file_id": file_id, "reason": f"parse failed: {error}"})
            continue
        if not units:
            gaps.append({"file_id": file_id, "reason": "no source units"})
            continue
        parsed.append((file_id, units, len(source.splitlines())))

    if not parsed:
        raise RuntimeError(
            f"no extractable source units in {workspace}; "
            f"checked {len(files)} files and recorded {len(gaps)} gaps"
        )

    packets = _packets(parsed, max_files=max_files, max_units=max_units)
    fingerprint = hashlib.sha256(
        json.dumps(
            [[file_id, hashlib.sha256((workspace / file_id).read_bytes()).hexdigest()]
             for file_id, _, _ in parsed],
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema": "migration-focus-context-packets-v1",
        "task_blind": True,
        "task_information_used": False,
        "task_id": config.get("task_id"),
        "scenario": scenario,
        "language": language,
        "backend_id": backend_id,
        "source": str(workspace),
        "source_sha256": fingerprint,
        "workspace_sha256": workspace_sha256,
        "workspace_files": workspace_files,
        "packet_config": {
            "extensions": sorted(extensions),
            "excluded_directory_names": sorted(excluded_dirs),
            "excluded_filenames": excluded_filenames,
            "max_file_bytes": max_file_bytes,
            "max_files_per_packet": max_files,
            "max_units_per_packet": max_units,
        },
        "source_file_count": len(parsed),
        "source_unit_count": sum(len(units) for _, units, _ in parsed),
        "packet_count": len(packets),
        "gaps": gaps,
        "packets": packets,
    }
    output = task_root / "inputs" / "focus_context_packets.json"
    if output.is_file():
        existing = load_json(output)
        if existing != payload:
            raise RuntimeError(f"preserving different frozen input: {output}")
    else:
        write_json(output, payload)
    return payload


def main() -> None:
    config = load_json(ROOT / "config.json")
    payload = build_inputs(config, task_root=ROOT)
    print(
        json.dumps(
            {
                "output": str(ROOT / "inputs" / "focus_context_packets.json"),
                "language": payload["language"],
                "source_file_count": payload["source_file_count"],
                "source_unit_count": payload["source_unit_count"],
                "packet_count": payload["packet_count"],
                "gaps": len(payload["gaps"]),
                "packets": [
                    {
                        "packet_id": packet["packet_id"],
                        "files": len(packet["visible_files"]),
                        "focus_units": packet["focus_unit_count"],
                    }
                    for packet in payload["packets"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()