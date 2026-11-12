"""Language-neutral skeleton evidence over backend-provided token streams."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from component_method.languages.base import SignalBackend
from component_method.languages.registry import default_backend
from .ngrams import NgramStream, find_shared_runs

DEFAULT_K = 3
DEFAULT_MIN_RUN = 9


def cluster_evidence(file_sources: list[dict[str, str]], k: int = DEFAULT_K, min_run: int = DEFAULT_MIN_RUN, *, backend: SignalBackend | None = None, max_stream_frequency: int = 0) -> dict[str, Any]:
    backend = backend or default_backend()
    streams: list[NgramStream] = []
    per_file_tokens: dict[str, int] = {}
    unit_tokens: dict[str, dict[str, int]] = {}
    errors: dict[str, str] = {}
    for entry in file_sources:
        file_id = entry["file_id"]
        unit_streams, error = backend.file_token_streams(file_id, entry["source_code"], "skeleton")
        streams.extend(NgramStream(stream.file_id, stream.unit_id, list(stream.tokens), list(stream.rows))
                       for stream in unit_streams)
        per_file_tokens[file_id] = sum(len(s.tokens) for s in unit_streams)
        unit_tokens[file_id] = {stream.unit_id: len(stream.tokens) for stream in unit_streams}
        if error:
            errors[file_id] = error

    runs = find_shared_runs(streams, k=k, min_run=min_run,
                            max_stream_frequency=max_stream_frequency)
    pair_units: dict[tuple[str, str], dict[tuple[str, str], dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"shared_tokens": 0, "n_runs": 0})
    )
    run_counts_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for run in runs:
        if run.file_a < run.file_b:
            pair = (run.file_a, run.file_b)
            unit_pair = (run.unit_a, run.unit_b)
        else:
            pair = (run.file_b, run.file_a)
            unit_pair = (run.unit_b, run.unit_a)
        run_counts_by_pair[pair] += 1
        pair_units[pair][unit_pair]["shared_tokens"] += run.tokens
        pair_units[pair][unit_pair]["n_runs"] += 1

    pairs: list[dict[str, Any]] = []
    for (file_a, file_b), unit_evidence in pair_units.items():
        shared_tokens = sum(item["shared_tokens"] for item in unit_evidence.values())
        tokens_a, tokens_b = per_file_tokens.get(file_a, 0), per_file_tokens.get(file_b, 0)
        pairs.append({
            "file_a": file_a,
            "file_b": file_b,
            "shared_tokens": shared_tokens,
            "n_runs": run_counts_by_pair[(file_a, file_b)],
            "tokens_a": tokens_a,
            "tokens_b": tokens_b,
            "containment": round(shared_tokens / max(min(tokens_a, tokens_b), 1), 4),
            "unit_pairs": [
                {
                    "file_a": file_a,
                    "unit_a": unit_a,
                    "file_b": file_b,
                    "unit_b": unit_b,
                    "shared_tokens": item["shared_tokens"],
                    "n_runs": item["n_runs"],
                    "tokens_a": unit_tokens.get(file_a, {}).get(unit_a, 0),
                    "tokens_b": unit_tokens.get(file_b, {}).get(unit_b, 0),
                    "containment": round(
                        item["shared_tokens"]
                        / max(
                            min(
                                unit_tokens.get(file_a, {}).get(unit_a, 0),
                                unit_tokens.get(file_b, {}).get(unit_b, 0),
                            ),
                            1,
                        ),
                        4,
                    ),
                }
                for (unit_a, unit_b), item in unit_evidence.items()
            ],
        })
    pairs.sort(key=lambda p: p["shared_tokens"], reverse=True)
    return {
        "signal": "skeleton",
        "k": k,
        "min_run": min_run,
        "per_file_tokens": per_file_tokens,
        "unit_tokens": unit_tokens,
        "parse_errors": errors,
        "pairs": pairs,
        "unit_pairs": [item for pair in pairs for item in pair["unit_pairs"]],
    }
