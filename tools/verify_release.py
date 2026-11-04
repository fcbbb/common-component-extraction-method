#!/usr/bin/env python3
"""Verify structure, metrics, hashes, and distribution hygiene of the release."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any


TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
RELEASE = REPOSITORY.parent
OFFLINE = RELEASE / "offline_artifacts"

EXPECTED_TASKS = [
    "qiskit-community__ffsim-248",
    "hikari-py__hikari-897",
    "yukinarit__pyserde-486",
    "elastic__curator-1085",
    "stingraysoftware__stingray-797",
    "cornellius-gp__gpytorch-296",
    "elastic__curator-1175",
    "pennylaneai__pennylane-3033",
    "neurodatawithoutborders__pynwb-557",
    "stfc__psyclone-1850",
    "pennylaneai__pennylane-3057",
    "xknx__xknx-1277",
    "pybamm-team__pybamm-1014",
    "census-instrumentation__opencensus-python-144",
    "sdv-dev__rdt-741",
    "jelmer__dulwich-1171",
    "nipype__pydra-742",
    "tefra__xsdata-310",
    "maniacallabs__bibliopixel-1105",
    "duartegroup__autode-349",
]

EXPECTED_FORMAL_ATTEMPTS = {
    "pennylaneai__pennylane-3057": "task_02",
    "pybamm-team__pybamm-1014": "task_02",
}

BANNED_NAMES = {
    "state.json",
    "checkpoint.traj.json",
    "tests.log",
    "launch.log",
    "worker.lock",
}

TEXT_SUFFIXES = {
    ".json", ".md", ".txt", ".yaml", ".yml", ".py", ".toml", ".sh", ".csv", ".patch"
}

SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]{16,}"),
]

FORBIDDEN_HOME_PREFIXES = (
    "/home/" + "fcbbbb/",
    "/home/" + "xiaoheng/",
)

GENERATED_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "work",
}

CACHE_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_json(path: Path) -> Any:
    require(path.is_file(), f"missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_npy_header(path: Path) -> tuple[dict[str, Any], int]:
    with path.open("rb") as source:
        require(source.read(6) == b"\x93NUMPY", f"not an NPY file: {path}")
        major, minor = source.read(2)
        if (major, minor) == (1, 0):
            header_length = struct.unpack("<H", source.read(2))[0]
        elif major in {2, 3}:
            header_length = struct.unpack("<I", source.read(4))[0]
        else:
            raise VerificationError(f"unsupported NPY version {major}.{minor}: {path}")
        header = ast.literal_eval(source.read(header_length).decode("latin1").strip())
        return header, source.tell()


def verify_metrics() -> list[dict[str, str]]:
    summary = read_json(REPOSITORY / "results/summary.json")
    require(summary["task_count"] == 20, "summary task count is not 20")
    require(summary["published_component_count"] == 486, "published component total is not 486")
    require(summary["selected_component_count"] == 63, "selected component total is not 63")
    require(summary["direct_passed"] == 6, "direct pass count is not 6")
    require(summary["component_passed"] == 10, "component pass count is not 10")
    require(summary["fail_to_pass_gains"] == 4, "failure-to-pass gain count is not 4")
    require(summary["pass_to_fail_regressions"] == 0, "unexpected pass-to-fail regression")
    require(summary["formal_reruns"] == EXPECTED_FORMAL_ATTEMPTS, "formal rerun map differs")

    with (REPOSITORY / "results/per_task.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    require([row["instance_id"] for row in rows] == EXPECTED_TASKS, "per-task order or membership differs")
    require(sum(row["direct_passed"] == "True" for row in rows) == 6, "CSV direct pass count differs")
    require(sum(row["component_passed"] == "True" for row in rows) == 10, "CSV component pass count differs")
    require(sum(int(row["component_count"]) for row in rows) == 486, "CSV component total differs")
    require(sum(int(row["selected_component_count"]) for row in rows) == 63, "CSV selection total differs")
    for row in rows:
        expected = EXPECTED_FORMAL_ATTEMPTS.get(row["instance_id"], "task_01")
        if row["instance_id"] == "nipype__pydra-742":
            expected = "task_attempt_07"
        require(row["final_component_attempt"] == expected, f"wrong final attempt for {row['instance_id']}")
    return rows


def verify_task_artifacts(rows: list[dict[str, str]]) -> None:
    task_root = OFFLINE / "tasks"
    actual = sorted(path.name for path in task_root.iterdir() if path.is_dir())
    require(actual == sorted(EXPECTED_TASKS), "offline task directory membership differs")
    direct_modes = reference_modes = 0
    source_files = 0
    for row in rows:
        task_id = row["instance_id"]
        root = task_root / task_id
        required = [
            root / "task.json",
            root / "evaluation_only/task_private.json",
            root / "provenance.json",
            root / "component_library/manifest.json",
            root / "retrieval/selected_component_bundle/selection.json",
            root / "outcomes/direct/result.json",
            root / "outcomes/direct/evaluation.json",
            root / "outcomes/direct/submitted.patch",
            root / "outcomes/components/result.json",
            root / "outcomes/components/evaluation.json",
            root / "outcomes/components/submitted.patch",
        ]
        for path in required:
            require(path.is_file(), f"missing task artifact: {path}")
        provenance = read_json(root / "provenance.json")
        library = read_json(root / "component_library/manifest.json")
        selection = read_json(root / "retrieval/selected_component_bundle/selection.json")
        require(provenance["component_count"] == int(row["component_count"]), f"component count differs for {task_id}")
        require(library["component_count"] == int(row["component_count"]), f"library count differs for {task_id}")
        selected = selection.get("selected", [])
        require(len(selected) == int(row["selected_component_count"]), f"selection count differs for {task_id}")
        direct_modes += sum(item.get("delivery_mode") == "direct_reuse" for item in selected)
        reference_modes += sum(item.get("delivery_mode") == "reference_pattern" for item in selected)
        source_files += sum(1 for path in (root / "source_snapshot").rglob("*.py") if path.is_file())
        private = read_json(root / "evaluation_only/task_private.json")
        require(private.get("warning", "").startswith("仅供评测使用"), f"missing evaluation-only warning for {task_id}")
    require(direct_modes == 13, f"direct-reuse selection count is {direct_modes}, expected 13")
    require(reference_modes == 50, f"reference-pattern selection count is {reference_modes}, expected 50")
    require(source_files == 2148, f"production source file count is {source_files}, expected 2148")


def verify_embeddings() -> None:
    root = OFFLINE / "embeddings"
    input_manifest = read_json(root / "input_manifest.json")
    result_manifest = read_json(root / "embedding_result_manifest.json")
    require(list(input_manifest["repositories"]) == EXPECTED_TASKS, "embedding repository order differs")
    require(input_manifest["unit_count"] == 26572, "embedding unit count is not 26,572")
    require(result_manifest["unit_count"] == 26572, "embedding result unit count differs")
    require(result_manifest["embedding_shape"] == [26572, 896], "embedding shape differs")
    require(sha256_file(root / "units.jsonl.gz") == input_manifest["units_file_sha256"], "units hash mismatch")
    require(sha256_file(root / "unit_embeddings.npy") == result_manifest["embedding_file_sha256"], "matrix hash mismatch")
    matrix_path = root / "unit_embeddings.npy"
    header, data_offset = read_npy_header(matrix_path)
    require(list(header["shape"]) == [26572, 896], "matrix file shape differs")
    require(header["descr"] in {"<f4", "=f4"}, "matrix dtype is not float32")
    require(not header["fortran_order"], "matrix is unexpectedly Fortran ordered")
    expected_bytes = data_offset + 26572 * 896 * 4
    require(matrix_path.stat().st_size == expected_bytes, "matrix byte length differs")


def verify_manifest(root: Path, manifest_path: Path) -> None:
    manifest = read_json(manifest_path)
    listed = {entry["path"]: entry for entry in manifest["files"]}
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and path != manifest_path
        and not path.is_symlink()
        and not any(part in GENERATED_DIRECTORIES for part in path.relative_to(root).parts)
        and not any(part.endswith(".egg-info") for part in path.relative_to(root).parts)
        and path.suffix not in {".pyc", ".pyo"}
    }
    require(set(listed) == set(actual), f"manifest membership differs: {manifest_path}")
    for relative, path in actual.items():
        entry = listed[relative]
        require(path.stat().st_size == entry["bytes"], f"size mismatch: {path}")
        require(sha256_file(path) == entry["sha256"], f"hash mismatch: {path}")


def verify_hygiene() -> None:
    errors = []
    expected_stages = (
        "source_scan",
        "signal_analysis",
        "protocol_candidates",
        "component_build",
        "library_publish",
        "retrieval",
        "task_execution",
        "reporting",
        "workflow",
    )
    for stage in expected_stages:
        require((REPOSITORY / "src/component_method" / stage).is_dir(), f"缺少阶段目录: {stage}")
    for path in RELEASE.rglob("*"):
        relative = path.relative_to(RELEASE).as_posix()
        release_parts = path.relative_to(RELEASE).parts
        if ".venv" in release_parts or any(
            part.endswith(".egg-info") for part in release_parts
        ) or (
            len(release_parts) >= 2
            and release_parts[0] == "repository"
            and release_parts[1] == "work"
        ):
            continue
        if any(part in CACHE_DIRECTORIES for part in release_parts) or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"Python cache artifact: {relative}")
            continue
        if path.is_symlink():
            errors.append(f"symlink: {relative}")
            continue
        if not path.is_file():
            continue
        if path.name in BANNED_NAMES or path.name.endswith(".traj.json") or path.name.endswith(".log"):
            errors.append(f"forbidden raw artifact: {relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 8 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(prefix in text for prefix in FORBIDDEN_HOME_PREFIXES):
            errors.append(f"absolute workspace path: {relative}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"credential-like string: {relative}")
                break
    require(not errors, "release hygiene failures:\n  " + "\n  ".join(errors[:40]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-hashes",
        action="store_true",
        help="Skip full repository and offline file-manifest hash verification.",
    )
    args = parser.parse_args()
    rows = verify_metrics()
    verify_task_artifacts(rows)
    verify_embeddings()
    verify_hygiene()
    if not args.skip_hashes:
        verify_manifest(REPOSITORY, REPOSITORY / "results/manifest.json")
        verify_manifest(OFFLINE, OFFLINE / "manifest.json")
    print("release verification passed")
    print("tasks=20 components=486 selected=63 direct=6 component=10 units=26572")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
