#!/usr/bin/env python3
"""Build a task-blind embedding corpus through registered source backends."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterator

from component_method.languages.registry import LanguageRegistry, default_backend
from component_method.source_scan.scanning import source_files, task_backends
from component_method.workflow.batch_common import PROJECT, ROOT, config, select_tasks, sha256_file, write_json


INPUT_SCHEMA = "featurebench-c2llm-offline-input-v2"


def eligible_files(snapshot_root: Path, source_subdir: str) -> Iterator[tuple[Path, str]]:
    """Compatibility entrypoint using the default backend's historical order."""
    for path in default_backend().eligible_files(snapshot_root, source_subdir):
        yield path, path.relative_to(snapshot_root).as_posix()


def prepare_corpus(chosen: list[dict[str, Any]], cfg: dict[str, Any], output_dir: Path,
                    project: Path, *, registry: LanguageRegistry | None = None) -> dict[str, Any]:
    selections = {task["instance_id"]: task_backends(task, registry, defaults=cfg) for task in chosen}
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "input_manifest.json"
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("schema") != INPUT_SCHEMA:
            raise RuntimeError("preserving legacy embedding input; choose a new output directory")
    units_path = output_dir / "units.jsonl.gz"
    task_stats: dict[str, dict[str, Any]] = {}
    unit_order_digest = hashlib.sha256()
    total_rows = 0
    with units_path.open("wb") as raw_output:
        with gzip.GzipFile(fileobj=raw_output, mode="wb", filename="", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as writer:
                for task in chosen:
                    instance_id = task["instance_id"]
                    snapshot_root = project / task["repository_root"]
                    selection = selections[instance_id]
                    row_start = total_rows
                    file_count = source_bytes = unit_count = unit_bytes = 0
                    source_digest = hashlib.sha256()
                    for entry, backend in source_files(snapshot_root, task["source_subdir"], selection):
                        file_id, source = entry["file_id"], entry["source_code"]
                        encoded_source = source.encode("utf-8")
                        source_sha256 = hashlib.sha256(encoded_source).hexdigest()
                        source_digest.update(file_id.encode("utf-8") + b"\0" + source_sha256.encode("ascii") + b"\n")
                        file_count += 1
                        source_bytes += len(encoded_source)
                        for unit in backend.extract_units(file_id, source):
                            unit_text = unit.source_code
                            unit_sha256 = hashlib.sha256(unit_text.encode("utf-8")).hexdigest()
                            # The alias is retained only for v1 candidate consumers.
                            unit_id = unit.metadata.get("legacy_unit_id", unit.unit_key)
                            row = {
                                **unit.to_json(), "repo_key": instance_id, "unit_id": unit_id,
                                "source_sha256": source_sha256, "unit_sha256": unit_sha256,
                            }
                            writer.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                            unit_order_digest.update(unit.unit_key.encode("ascii") + b"\n")
                            unit_count += 1
                            unit_bytes += len(unit_text.encode("utf-8"))
                            total_rows += 1
                    if not unit_count:
                        raise RuntimeError(f"no code units found for {instance_id}")
                    task_stats[instance_id] = {
                        "cohort": task["cohort"], "repo": task["repo"], "base_commit": task["base_commit"],
                        "source_subdir": task["source_subdir"], "repository_root": task["repository_root"],
                        "eligible_files": file_count, "units": unit_count, "row_start": row_start,
                        "row_end_exclusive": total_rows, "source_bytes": source_bytes, "unit_bytes": unit_bytes,
                        "source_manifest_sha256": source_digest.hexdigest(),
                    }
                    print(f"[prepare] {instance_id}: files={file_count} units={unit_count}", flush=True)
    embedding = cfg["embedding"]
    manifest = {
        "schema": INPUT_SCHEMA, "round_id": cfg["experiment_id"],
        "model_id": embedding["model_id"], "model_revision": embedding["model_revision"],
        "unit_extractor": "LanguageBackend.extract_units", "unit_schema": "source-unit-v2",
        "language_backends": {key: selection.manifest() for key, selection in selections.items()},
        "unit_count": total_rows, "unit_order_sha256": unit_order_digest.hexdigest(),
        "units_file": units_path.name, "units_file_sha256": sha256_file(units_path),
        "units_file_bytes": units_path.stat().st_size,
        "scan_policy": {
            "scope": "configured production package root per frozen repository snapshot",
            "ordering": "configured backend id, then backend production traversal",
            "repositories": {
                key: {backend.backend_id: backend.scan_policy() for backend, _ in selection.entries}
                for key, selection in selections.items()
            },
        },
        "embedding_policy": {
            "normalization": "L2", "similarity": "dot product of normalized vectors",
            "max_seq_length": embedding["max_seq_length"], "batch_size_reference": embedding["batch_size"],
        },
        "repositories": task_stats,
        "task_blindness": {
            "task_statements_included": False, "target_test_contents_included": False,
            "gold_annotations_included": False, "gold_patches_included": False, "production_source_only": True,
        },
    }
    write_json(manifest_path, manifest)
    print(f"[prepare] wrote {total_rows} units across {len(chosen)} snapshots", flush=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", help="Limit to task IDs; repeatable.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "offline_embedding_50tasks_20261024")
    args = parser.parse_args()
    prepare_corpus(select_tasks(args.task, include_reserve=True), config(), args.output_dir.resolve(), PROJECT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
