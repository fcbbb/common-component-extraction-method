#!/usr/bin/env python3
"""Compute normalized C2LLM vectors, reusing validated rows from the old five-task matrix."""

from __future__ import annotations

import argparse
import builtins
from datetime import datetime, timezone
import gzip
import hashlib
import inspect
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator

from component_method.workflow.batch_common import PROJECT, ROOT, config, sha256_file, write_json


if not hasattr(builtins, "is_torch_npu_available"):
    builtins.is_torch_npu_available = lambda: False


def read_batches(path: Path, batch_size: int) -> Iterator[list[dict[str, Any]]]:
    batch = []
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            row = json.loads(line)
            if not all(key in row for key in ("unit_key", "unit_sha256", "source_code")):
                raise RuntimeError(f"input row {line_number} lacks required fields")
            batch.append(row)
            if len(batch) == batch_size:
                yield batch
                batch = []
    if batch:
        yield batch


def load_reuse(reuse_dir: Path, input_manifest: dict[str, Any]):
    import numpy as np

    manifest_path = reuse_dir / "input_manifest.json"
    result_path = reuse_dir / "embedding_result_manifest.json"
    units_path = reuse_dir / "units.jsonl.gz"
    matrix_path = reuse_dir / "unit_embeddings.npy"
    if not all(path.is_file() for path in (manifest_path, result_path, units_path, matrix_path)):
        raise RuntimeError(f"incomplete reuse directory: {reuse_dir}")
    old_input = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_result = json.loads(result_path.read_text(encoding="utf-8"))
    if old_input.get("schema") == "featurebench-c2llm-offline-input-v2":
        if old_result.get("input_manifest_sha256") != sha256_file(manifest_path):
            raise RuntimeError("reuse input manifest hash mismatch")
    if old_input["model_id"] != input_manifest["model_id"]:
        raise RuntimeError("reuse model ID differs")
    if old_input["model_revision"] != input_manifest["model_revision"]:
        raise RuntimeError("reuse model revision differs")
    if old_input["embedding_policy"]["max_seq_length"] != input_manifest["embedding_policy"]["max_seq_length"]:
        raise RuntimeError("reuse max sequence length differs")
    if old_result["units_file_sha256"] != sha256_file(units_path):
        raise RuntimeError("reuse units hash mismatch")
    if old_result["embedding_file_sha256"] != sha256_file(matrix_path):
        raise RuntimeError("reuse matrix hash mismatch")
    matrix = np.load(matrix_path, mmap_mode="r")
    if list(matrix.shape) != old_result["embedding_shape"]:
        raise RuntimeError("reuse matrix shape mismatch")
    index = {}
    with gzip.open(units_path, "rt", encoding="utf-8") as source:
        for row_number, line in enumerate(source):
            row = json.loads(line)
            if not reuse_backend_matches(old_input, input_manifest, row["repo_key"]):
                continue
            index[row["unit_key"]] = (row["unit_sha256"], row_number)
    return old_input, old_result, matrix, index


def reuse_backend_matches(old_input: dict[str, Any], new_input: dict[str, Any], repository: str) -> bool:
    old = old_input.get("language_backends")
    new = new_input.get("language_backends")
    if old is None and new is None:
        return old_input.get("schema") == new_input.get("schema") == "featurebench-c2llm-offline-input-v1"
    return (isinstance(old, dict) and isinstance(new, dict)
            and repository in old and repository in new and old[repository] == new[repository])


def completed_output_matches(result: dict[str, Any], input_manifest: dict[str, Any],
                              input_path: Path, manifest_path: Path, output_path: Path) -> bool:
    return (
        result.get("input_manifest_sha256") == sha256_file(manifest_path)
        and result.get("units_file_sha256") == sha256_file(input_path)
        and result.get("unit_order_sha256") == input_manifest["unit_order_sha256"]
        and result.get("embedding_file_sha256") == sha256_file(output_path)
    )


def main() -> int:
    cfg = config()
    embedding_cfg = cfg["embedding"]
    default_dir = (
        ROOT
        if (ROOT / "input_manifest.json").is_file()
        else ROOT / "offline_embedding_50tasks_20261024"
    )
    packaged_reuse = default_dir / "bootstrap_5tasks"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=default_dir / "units.jsonl.gz")
    parser.add_argument("--input-manifest", type=Path, default=default_dir / "input_manifest.json")
    parser.add_argument("--output", type=Path, default=default_dir / "unit_embeddings.npy")
    parser.add_argument("--result-manifest", type=Path, default=default_dir / "embedding_result_manifest.json")
    parser.add_argument(
        "--reuse-dir",
        type=Path,
        default=packaged_reuse if packaged_reuse.is_dir() else PROJECT / cfg["bootstrap_embeddings"],
    )
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=embedding_cfg["batch_size"])
    parser.add_argument("--chunk-size", type=int, default=embedding_cfg["chunk_size"])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    input_path = args.input.resolve()
    input_manifest_path = args.input_manifest.resolve()
    output_path = args.output.resolve()
    result_manifest_path = args.result_manifest.resolve()
    if args.batch_size < 1 or args.chunk_size < args.batch_size:
        raise RuntimeError("batch-size must be positive and chunk-size must be >= batch-size")
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    if input_manifest.get("schema") not in {
        "featurebench-c2llm-offline-input-v1", "featurebench-c2llm-offline-input-v2"
    }:
        raise RuntimeError("unsupported input manifest schema")
    if input_manifest.get("units_file_sha256") != sha256_file(input_path):
        raise RuntimeError("units hash does not match input manifest")
    if args.resume and output_path.is_file() and result_manifest_path.is_file():
        result = json.loads(result_manifest_path.read_text(encoding="utf-8"))
        if completed_output_matches(result, input_manifest, input_path, input_manifest_path, output_path):
            print(f"[embed] valid output already exists: {output_path}")
            return 0

    import numpy as np
    import torch
    import sentence_transformers
    from sentence_transformers import SentenceTransformer

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    old_input, old_result, reuse_matrix, reuse_index = load_reuse(
        args.reuse_dir.resolve(), input_manifest
    )
    dimension = int(reuse_matrix.shape[1])
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    result_matrix = np.lib.format.open_memmap(
        partial_path,
        mode="w+",
        dtype=np.float32,
        shape=(int(input_manifest["unit_count"]), dimension),
    )
    started = time.monotonic()
    model = None
    parameter_dtype = old_result.get("parameter_dtype")
    row_offset = reused_rows = computed_rows = 0
    reused_repositories: set[str] = set()
    unit_order_digest = hashlib.sha256()
    max_norm_error = 0.0

    def ensure_model():
        nonlocal model, parameter_dtype
        if model is None:
            model = SentenceTransformer(
                input_manifest["model_id"],
                revision=input_manifest["model_revision"],
                trust_remote_code=True,
                device=args.device,
                model_kwargs={"attn_implementation": "eager"},
            )
            model.max_seq_length = int(input_manifest["embedding_policy"]["max_seq_length"])
            for module in model:
                if hasattr(module, "auto_model") and getattr(module, "model_forward_params", None) is None:
                    module.model_forward_params = set(inspect.signature(module.auto_model.forward).parameters)
            parameter_dtype = str(next(model.parameters()).dtype)
        return model

    for rows in read_batches(input_path, args.chunk_size):
        vectors = np.empty((len(rows), dimension), dtype=np.float32)
        missing_positions = []
        missing_texts = []
        for position, row in enumerate(rows):
            reused = reuse_index.get(row["unit_key"])
            if reused and reused[0] == row["unit_sha256"]:
                vectors[position] = reuse_matrix[reused[1]]
                reused_rows += 1
                reused_repositories.add(row["repo_key"])
            else:
                missing_positions.append(position)
                missing_texts.append(row["source_code"])
        if missing_texts:
            fresh = ensure_model().encode(
                missing_texts,
                batch_size=args.batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            fresh = np.asarray(fresh, dtype=np.float32)
            if fresh.shape != (len(missing_texts), dimension):
                raise RuntimeError(f"unexpected fresh embedding shape: {fresh.shape}")
            vectors[np.asarray(missing_positions)] = fresh
            computed_rows += len(missing_texts)
        if not np.isfinite(vectors).all():
            raise RuntimeError("embedding chunk contains non-finite values")
        norm_error = float(np.max(np.abs(np.linalg.norm(vectors, axis=1) - 1.0)))
        max_norm_error = max(max_norm_error, norm_error)
        if norm_error > 0.02:
            raise RuntimeError(f"embeddings are not normalized: {norm_error:.5f}")
        end = row_offset + len(rows)
        result_matrix[row_offset:end] = vectors
        for row in rows:
            unit_order_digest.update(row["unit_key"].encode("ascii") + b"\n")
        row_offset = end
        print(
            f"[embed] rows={row_offset}/{input_manifest['unit_count']} "
            f"reused={reused_rows} computed={computed_rows}",
            flush=True,
        )
    if row_offset != int(input_manifest["unit_count"]):
        raise RuntimeError("embedded row count differs from input manifest")
    if unit_order_digest.hexdigest() != input_manifest["unit_order_sha256"]:
        raise RuntimeError("unit order hash mismatch")
    result_matrix.flush()
    del result_matrix
    os.replace(partial_path, output_path)
    device_info: dict[str, Any] = {"requested": args.device}
    if args.device == "cuda":
        device_info.update(
            name=torch.cuda.get_device_name(0),
            total_memory_bytes=torch.cuda.get_device_properties(0).total_memory,
        )
    result = {
        "schema": ("featurebench-c2llm-offline-output-v2" if "language_backends" in input_manifest
                   else "featurebench-c2llm-offline-output-v1"),
        **({"language_backends": input_manifest["language_backends"]} if "language_backends" in input_manifest else {}),
        "model_id": input_manifest["model_id"],
        "model_revision_requested": input_manifest["model_revision"],
        "model_revision_resolved": input_manifest["model_revision"],
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "units_file_sha256": sha256_file(input_path),
        "unit_order_sha256": unit_order_digest.hexdigest(),
        "unit_count": row_offset,
        "embedding_file": output_path.name,
        "embedding_file_sha256": sha256_file(output_path),
        "embedding_shape": [row_offset, dimension],
        "embedding_dtype": "float32",
        "normalized": True,
        "max_l2_norm_error": max_norm_error,
        "max_seq_length": input_manifest["embedding_policy"]["max_seq_length"],
        "parameter_dtype": parameter_dtype,
        "batch_size": args.batch_size,
        "chunk_size": args.chunk_size,
        "device": device_info,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "sentence_transformers_version": sentence_transformers.__version__,
        "reuse": {
            "source": str(args.reuse_dir.resolve()),
            "source_input_manifest_sha256": sha256_file(args.reuse_dir.resolve() / "input_manifest.json"),
            "source_result_manifest_sha256": sha256_file(args.reuse_dir.resolve() / "embedding_result_manifest.json"),
            "reused_rows": reused_rows,
            "computed_rows": computed_rows,
            "reused_repositories": sorted(reused_repositories),
        },
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    write_json(result_manifest_path, result)
    print(f"[embed] wrote {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
