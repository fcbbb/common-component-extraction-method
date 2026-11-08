#!/usr/bin/env python3
"""Validate the 50-task matrix and build frozen recall signals and V2 candidates."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any

import hnswlib
import numpy as np

from component_method.workflow.batch_common import PROJECT, ROOT, config, select_tasks, sha256_file, write_json
from component_method.languages.contracts import stable_digest
from component_method.languages.graph import GraphBackend
from component_method.source_scan.scanning import source_files, task_backends


ANN_SEED = 20261024
from component_method.signal_analysis import ast_signal, clone_signal, fusion  # noqa: E402
from component_method.protocol_candidates import protocol_recall  # noqa: E402


def read_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return [json.loads(line) for line in source]


def validate_matrix(embedding_dir: Path):
    input_path = embedding_dir / "input_manifest.json"
    result_path = embedding_dir / "embedding_result_manifest.json"
    units_path = embedding_dir / "units.jsonl.gz"
    matrix_path = embedding_dir / "unit_embeddings.npy"
    input_manifest = json.loads(input_path.read_text(encoding="utf-8"))
    result_manifest = json.loads(result_path.read_text(encoding="utf-8"))
    checks = {
        "input_manifest_sha256": sha256_file(input_path),
        "units_file_sha256": sha256_file(units_path),
        "embedding_file_sha256": sha256_file(matrix_path),
    }
    for key, actual in checks.items():
        if result_manifest.get(key) != actual:
            raise RuntimeError(f"{key} mismatch")
    if result_manifest["unit_order_sha256"] != input_manifest["unit_order_sha256"]:
        raise RuntimeError("unit order differs between manifests")
    rows = read_rows(units_path)
    matrix = np.load(matrix_path, mmap_mode="r")
    if list(matrix.shape) != result_manifest["embedding_shape"] or len(rows) != matrix.shape[0]:
        raise RuntimeError("matrix shape differs from frozen units")
    return input_manifest, result_manifest, rows, matrix


def collect_sources(task: dict[str, Any]) -> list[dict[str, str]]:
    snapshot = PROJECT / task["repository_root"]
    return [{**entry, "language": backend.language_id, "backend_id": backend.backend_id}
            for entry, backend in source_files(snapshot, task["source_subdir"], task_backends(task))]


def validate_units(task: dict[str, Any], frozen_rows: list[dict[str, Any]]):
    sources = collect_sources(task)
    backends = {backend.language_id: backend for backend, _ in task_backends(task).entries}
    for backend in backends.values():
        if hasattr(backend, "set_repository"):
            backend.set_repository(PROJECT / task["repository_root"])
    generated = [unit for source in sources for unit in
                 backends[source["language"]].extract_units(source["file_id"], source["source_code"])]
    structured = bool(frozen_rows and frozen_rows[0].get("schema") == "source-unit-v2")
    def identity(unit):
        return unit.unit_key if structured else (unit.file_id, unit.metadata.get("legacy_unit_id", unit.unit_key))

    generated_hashes = {
        identity(unit): hashlib.sha256(
            unit.source_code.encode("utf-8")
        ).hexdigest()
        for unit in generated
    }
    frozen_hashes = {
        (row["unit_key"] if structured else (row["file_id"], row["unit_id"])): row["unit_sha256"] for row in frozen_rows
    }
    if generated_hashes != frozen_hashes:
        missing = sorted(frozen_hashes.keys() - generated_hashes.keys())[:5]
        extra = sorted(generated_hashes.keys() - frozen_hashes.keys())[:5]
        changed = sorted(
            key for key in generated_hashes.keys() & frozen_hashes.keys()
            if generated_hashes[key] != frozen_hashes[key]
        )[:5]
        raise RuntimeError(
            f"{task['instance_id']} units changed: missing={missing} extra={extra} changed={changed}"
        )
    source_hashes = {
        source["file_id"]: hashlib.sha256(source["source_code"].encode("utf-8")).hexdigest()
        for source in sources
    }
    if any(row.get("source_sha256") is not None
           and row["source_sha256"] != source_hashes.get(row["file_id"]) for row in frozen_rows):
        raise RuntimeError(f"{task['instance_id']} source changed, including source coordinates")
    units = [
        {**row, "language": row.get("language", next(iter(backends))),
         "unit_id": row["unit_key"] if structured else row["unit_id"]}
        for row in frozen_rows
    ]
    return sources, units


def cross_file_pairs(embeddings: np.ndarray, units: list[dict[str, str]], top_k: int):
    count, dimension = embeddings.shape
    if count < 2:
        return [], {"method": "hnswlib", "query_k_max": count, "rounds": 0}
    index = hnswlib.Index(space="cosine", dim=dimension)
    index.init_index(max_elements=count, ef_construction=160, M=24, random_seed=ANN_SEED)
    index.add_items(embeddings, np.arange(count))
    selected_by_source: list[list[int] | None] = [None] * count
    pending = np.arange(count)
    query_k = min(count, max(top_k * 4 + 1, top_k + 1))
    rounds = 0
    while len(pending):
        rounds += 1
        index.set_ef(max(160, query_k * 2))
        labels, _ = index.knn_query(embeddings[pending], k=query_k, num_threads=-1)
        unresolved = []
        for source, neighbors in zip(pending.tolist(), labels):
            kept = []
            source_file = units[source]["file_id"]
            for raw_target in neighbors:
                target = int(raw_target)
                if target == source or units[target]["file_id"] == source_file:
                    continue
                kept.append(target)
                if len(kept) == top_k:
                    break
            if len(kept) == top_k or query_k == count:
                selected_by_source[source] = kept
            else:
                unresolved.append(source)
        if not unresolved:
            break
        pending = np.asarray(unresolved, dtype=np.int64)
        query_k = min(count, query_k * 2)
    selected = set()
    for source, targets in enumerate(selected_by_source):
        if targets is None:
            raise RuntimeError(f"Top-K left source {source} unresolved")
        for target in targets:
            selected.add((source, target) if source < target else (target, source))
    pair_indices = sorted(selected)
    pairs = []
    for start in range(0, len(pair_indices), 10_000):
        chunk = pair_indices[start:start + 10_000]
        left = np.fromiter((item[0] for item in chunk), dtype=np.int64)
        right = np.fromiter((item[1] for item in chunk), dtype=np.int64)
        cosines = np.einsum("ij,ij->i", embeddings[left], embeddings[right])
        for (a, b), cosine in zip(chunk, cosines.tolist()):
            pairs.append(
                {
                    "file_a": units[a]["file_id"],
                    "unit_a": units[a]["unit_id"],
                    "file_b": units[b]["file_id"],
                    "unit_b": units[b]["unit_id"],
                    "cosine": round(float(cosine), 6),
                }
            )
    pairs.sort(key=lambda item: item["cosine"], reverse=True)
    return pairs, {
        "method": "hnswlib_adaptive_cross_file",
        "top_k": top_k,
        "query_k_max": query_k,
        "rounds": rounds,
        "unit_count": count,
        "pair_count": len(pairs),
        "cross_file_only": True,
        "ann_seed": ANN_SEED,
    }


def build_task(
    task: dict[str, Any],
    candidate_cfg: dict[str, Any],
    input_manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    matrix: np.ndarray,
    *,
    resume: bool,
    reuse_frozen: bool,
) -> None:
    instance_id = task["instance_id"]
    task_root = ROOT / "tasks" / instance_id
    signal_root = task_root / "signals"
    candidate_root = task_root / "candidates"
    status_path = candidate_root / "status.json"
    candidate_path = candidate_root / "protocol_candidates_v2.json"
    selection = task_backends(task)
    for backend, _ in selection.entries:
        if hasattr(backend, "set_repository"):
            backend.set_repository(PROJECT / task["repository_root"])
    backend_manifest = selection.manifest()
    if input_manifest.get("schema") == "featurebench-c2llm-offline-input-v2":
        recorded = input_manifest.get("language_backends", {}).get(instance_id)
        if recorded != backend_manifest:
            raise RuntimeError(f"{instance_id} backend identity or path rules changed; prepare embedding input again")
    started = time.monotonic()
    info = input_manifest["repositories"][instance_id]
    start, end = info["row_start"], info["row_end_exclusive"]
    frozen_rows = rows[start:end]
    if any(row["repo_key"] != instance_id for row in frozen_rows):
        raise RuntimeError(f"row range contains another repository: {instance_id}")
    sources, units = validate_units(task, frozen_rows)
    fingerprint = stable_digest({
        "schema": "candidate-build-input-v2", "language_backends": backend_manifest,
        "embedding_input": input_manifest, "candidate_config": candidate_cfg,
        "vectors_sha256": hashlib.sha256(memoryview(np.ascontiguousarray(matrix[start:end]))).hexdigest(),
        "reuse_frozen": bool(reuse_frozen and task.get("frozen_candidate")),
        "frozen_candidate_sha256": (
            sha256_file(PROJECT / task["frozen_candidate"])
            if reuse_frozen and task.get("frozen_candidate") else None
        ),
    })
    if resume and status_path.is_file() and candidate_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if (status.get("status") == "ok" and status.get("candidate_sha256") == sha256_file(candidate_path)
                and status.get("input_fingerprint") == fingerprint):
            print(f"[candidate] reuse completed {instance_id}", flush=True)
            return
    write_json(signal_root / "semantic_input.json", {"files": sources})
    write_json(
        signal_root / "source_manifest.json",
        {
            "instance_id": instance_id,
            "file_count": len(sources),
            "files": [entry["file_id"] for entry in sources],
            "source_manifest_sha256": info["source_manifest_sha256"],
            "language_backends": backend_manifest,
        },
    )
    partitions = []
    for backend, _ in selection.entries:
        indices = [i for i, unit in enumerate(units) if unit["language"] == backend.language_id]
        language_units = [units[i] for i in indices]
        language_sources = [s for s in sources if s["language"] == backend.language_id]
        graph = GraphBackend(backend, [u for s in language_sources for u in
                                     backend.extract_units(s["file_id"], s["source_code"])])
        pairs, retrieval = cross_file_pairs(np.asarray(matrix[start:end])[indices], language_units,
                                            int(candidate_cfg["semantic_top_k"]))
        semantic = {"signal": "semantic", "model": input_manifest["model_id"],
                    "model_revision": input_manifest["model_revision"],
                    "max_seq_length": input_manifest["embedding_policy"]["max_seq_length"],
                    "units": [{"file_id": u["file_id"], "unit_id": u["unit_id"]} for u in language_units],
                    "pairs": pairs, "retrieval": retrieval}
        signal_backend = graph if graph.ambiguous_aliases else backend
        clone = clone_signal.cluster_evidence(language_sources, backend=signal_backend)
        skeleton = ast_signal.cluster_evidence(language_sources, backend=signal_backend)
        signals = [graph.signal(value) for value in (clone, skeleton, semantic)]
        strict = graph.candidates(fusion.fuse_units(
            signals, cfg=copy.deepcopy(candidate_cfg["strict_fusion"]), backend=graph))
        protocol = graph.candidates(protocol_recall.recall_candidates(
            language_sources, signals, cfg=candidate_cfg["protocol_recall"], backend=graph))
        partitions.append({"language": backend.language_id, "backend_id": backend.backend_id,
                           "semantic_topk": semantic, "clone": clone, "skeleton": skeleton,
                           "strict_candidates": strict, "protocol": protocol})
    def combined(key):
        if len(partitions) == 1:
            return partitions[0][key]
        values = [p[key] for p in partitions]
        return {"schema": "language-partitioned-candidates-v2",
                "partitions": [{"language": p["language"], "backend_id": p["backend_id"],
                                **p[key]} for p in partitions],
                "candidates": [c for value in values for c in value.get("candidates", [])],
                "unit_pairs": [c for value in values for c in value.get("unit_pairs", [])]}
    for name in ("semantic_topk", "clone", "skeleton"):
        write_json(signal_root / f"{name}.json", combined(name))
    strict, clone, skeleton = (combined(key) for key in ("strict_candidates", "clone", "skeleton"))
    pairs = [pair for p in partitions for pair in p["semantic_topk"]["pairs"]]
    write_json(candidate_root / "strict_candidates.json", strict)
    provenance: dict[str, Any]
    if reuse_frozen and task.get("frozen_candidate"):
        source = PROJECT / task["frozen_candidate"]
        candidate_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, candidate_path)
        protocol = json.loads(candidate_path.read_text(encoding="utf-8"))
        provenance = {
            "mode": "copied_frozen_v2_candidate",
            "source": task["frozen_candidate"],
            "source_sha256": sha256_file(source),
        }
    else:
        print(f"[candidate] protocol expansion {instance_id}", flush=True)
        protocol = combined("protocol")
        write_json(candidate_path, protocol)
        provenance = {
            "mode": "generated_from_frozen_50_task_embedding",
            "embedding_manifest": str(
                (ROOT / "offline_embedding_50tasks_20261024" / "embedding_result_manifest.json").relative_to(PROJECT)
            ),
        }
    file_counts = Counter(unit["file_id"] for unit in units)
    write_json(
        status_path,
        {
            "status": "ok",
            "schema": "candidate-build-status-v2",
            "input_fingerprint": fingerprint,
            "language_backends": backend_manifest,
            "legacy_embedding_input": input_manifest.get("schema") == "featurebench-c2llm-offline-input-v1",
            "instance_id": instance_id,
            "cohort": task["cohort"],
            "file_count": len(sources),
            "unit_count": len(units),
            "max_units_per_file": max(file_counts.values(), default=0),
            "semantic_pairs": len(pairs),
            "clone_unit_pairs": len(clone.get("unit_pairs", [])),
            "skeleton_unit_pairs": len(skeleton.get("unit_pairs", [])),
            "strict_candidates": len(strict.get("candidates", [])),
            "protocol_candidates": len(protocol.get("candidates", [])),
            "selection_policy": protocol.get("stats", {}).get("selection_policy"),
            "candidate_sha256": sha256_file(candidate_path),
            "provenance": provenance,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append")
    parser.add_argument("--include-reserve", action="store_true")
    parser.add_argument(
        "--embedding-dir",
        type=Path,
        default=PROJECT / "offline_artifacts" / "embeddings",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--regenerate-frozen-candidates", action="store_true")
    args = parser.parse_args()
    cfg = config()
    candidate_cfg = json.loads((PROJECT / cfg["candidate_config"]).read_text(encoding="utf-8"))
    input_manifest, _, rows, matrix = validate_matrix(args.embedding_dir.resolve())
    chosen = select_tasks(args.task, include_reserve=args.include_reserve)
    for task in chosen:
        build_task(
            task,
            candidate_cfg,
            input_manifest,
            rows,
            matrix,
            resume=args.resume,
            reuse_frozen=not args.regenerate_frozen_candidates,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
