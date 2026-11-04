#!/usr/bin/env python3
"""Build one task-blind C2LLM input corpus for all 50 frozen snapshots."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from component_method.workflow.batch_common import PROJECT, ROOT, config, select_tasks, sha256_file, write_json


EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "site-packages", "node_modules",
    "build", "dist", "vendor", "third_party", "generated", "test", "tests",
}


def eligible_files(snapshot_root: Path, source_subdir: str) -> Iterator[tuple[Path, str]]:
    scan_root = snapshot_root / source_subdir
    if not scan_root.is_dir():
        raise RuntimeError(f"source root is missing: {scan_root}")
    for current, dirs, names in os.walk(scan_root, topdown=True, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        for name in sorted(names):
            if not name.endswith(".py") or name.startswith("test_") or name.endswith("_test.py"):
                continue
            path = Path(current) / name
            relative = path.relative_to(snapshot_root)
            inside_source_root = path.relative_to(scan_root)
            if any(part in EXCLUDED_DIRS for part in inside_source_root.parts[:-1]):
                continue
            yield path, relative.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", help="Limit to task IDs; repeatable.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "offline_embedding_50tasks_20261024",
    )
    args = parser.parse_args()
    cfg = config()
    chosen = select_tasks(args.task, include_reserve=True)
    output_dir = args.output_dir.resolve()
    extractor_path = Path(__file__).resolve().parents[1] / "source_scan/unit_extraction.py"
    from component_method.source_scan.unit_extraction import _unit_sources

    output_dir.mkdir(parents=True, exist_ok=True)
    units_path = output_dir / "units.jsonl.gz"
    task_stats: dict[str, dict[str, Any]] = {}
    unit_order_digest = hashlib.sha256()
    total_rows = 0
    with units_path.open("wb") as raw_output:
        with gzip.GzipFile(fileobj=raw_output, mode="wb", filename="", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as writer:
                for task in chosen:
                    instance_id = task["instance_id"]
                    snapshot_root = PROJECT / task["repository_root"]
                    row_start = total_rows
                    file_count = source_bytes = unit_count = unit_bytes = 0
                    source_digest = hashlib.sha256()
                    for path, file_id in eligible_files(snapshot_root, task["source_subdir"]):
                        try:
                            source = path.read_text(encoding="utf-8")
                        except (UnicodeDecodeError, OSError):
                            continue
                        if not source.strip():
                            continue
                        encoded_source = source.encode("utf-8")
                        source_sha256 = hashlib.sha256(encoded_source).hexdigest()
                        source_digest.update(
                            file_id.encode("utf-8") + b"\0" + source_sha256.encode("ascii") + b"\n"
                        )
                        file_count += 1
                        source_bytes += len(encoded_source)
                        for unit in _unit_sources([{"file_id": file_id, "source_code": source}]):
                            unit_text = unit["source_code"]
                            unit_sha256 = hashlib.sha256(unit_text.encode("utf-8")).hexdigest()
                            identity = f"{instance_id}\0{file_id}\0{unit['unit_id']}"
                            unit_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                            row = {
                                "repo_key": instance_id,
                                "file_id": file_id,
                                "unit_id": unit["unit_id"],
                                "unit_key": unit_key,
                                "source_sha256": source_sha256,
                                "unit_sha256": unit_sha256,
                                "source_code": unit_text,
                            }
                            writer.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                            unit_order_digest.update(unit_key.encode("ascii") + b"\n")
                            unit_count += 1
                            unit_bytes += len(unit_text.encode("utf-8"))
                            total_rows += 1
                    if not unit_count:
                        raise RuntimeError(f"no Python code units found for {instance_id}")
                    task_stats[instance_id] = {
                        "cohort": task["cohort"],
                        "repo": task["repo"],
                        "base_commit": task["base_commit"],
                        "source_subdir": task["source_subdir"],
                        "repository_root": task["repository_root"],
                        "eligible_files": file_count,
                        "units": unit_count,
                        "row_start": row_start,
                        "row_end_exclusive": total_rows,
                        "source_bytes": source_bytes,
                        "unit_bytes": unit_bytes,
                        "source_manifest_sha256": source_digest.hexdigest(),
                    }
                    print(f"[prepare] {instance_id}: files={file_count} units={unit_count}", flush=True)

    embedding = cfg["embedding"]
    manifest = {
        "schema": "featurebench-c2llm-offline-input-v1",
        "round_id": cfg["experiment_id"],
        "model_id": embedding["model_id"],
        "model_revision": embedding["model_revision"],
        "unit_extractor": "component_method.source_scan.unit_extraction.extract_unit_sources",
        "unit_extractor_sha256": sha256_file(extractor_path),
        "unit_count": total_rows,
        "unit_order_sha256": unit_order_digest.hexdigest(),
        "units_file": units_path.name,
        "units_file_sha256": sha256_file(units_path),
        "units_file_bytes": units_path.stat().st_size,
        "scan_policy": {
            "scope": "configured production package root per frozen repository snapshot",
            "extensions": [".py"],
            "excluded_directory_names": sorted(EXCLUDED_DIRS),
            "excluded_filenames": ["test_*.py", "*_test.py"],
            "max_file_bytes": None,
        },
        "embedding_policy": {
            "normalization": "L2",
            "similarity": "dot product of normalized vectors",
            "max_seq_length": embedding["max_seq_length"],
            "batch_size_reference": embedding["batch_size"],
        },
        "repositories": task_stats,
        "task_blindness": {
            "task_statements_included": False,
            "target_test_contents_included": False,
            "gold_annotations_included": False,
            "gold_patches_included": False,
            "production_source_only": True,
        },
    }
    write_json(output_dir / "input_manifest.json", manifest)
    print(f"[prepare] wrote {total_rows} units across {len(chosen)} snapshots", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
