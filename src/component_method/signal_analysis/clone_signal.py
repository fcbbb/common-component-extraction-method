"""S1 verbatim signal: normalized-token clone detection (CCFinder-style, python-native).

Names are kept verbatim so this captures true copy-paste sharing; strings/numbers
collapse to placeholders so only literals differ.  Compare unit-level streams across
files, find maximal shared runs, then aggregate evidence per file pair.
"""
from __future__ import annotations

import ast
import io
import tokenize
from collections import defaultdict
from typing import Any

from .ngrams import NgramStream, SharedRun, find_shared_runs
from component_method.source_scan.units import container_of_row, parse_units

DEFAULT_K = 6
DEFAULT_MIN_RUN = 12


def _normalized_tokens(source: str) -> list[tuple[str, int]]:
    """(token_text, start_row) pairs, comments/whitespace stripped, STRING->str NUMBER->num."""
    out: list[tuple[str, int]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type in (tokenize.ENCODING, tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            text = tok.string
            if tok.type == tokenize.STRING:
                text = "str"
            elif tok.type == tokenize.NUMBER:
                text = "num"
            out.append((text, tok.start[0]))
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _unit_streams(file_id: str, source: str) -> tuple[list[NgramStream], list[Unit] | None]:
    tree, units, error = parse_units(source)
    if tree is None or units is None:
        # Unparseable file: fall back to a single module-level stream.
        tokens = _normalized_tokens(source)
        return [NgramStream(file_id, "module", [t for t, _ in tokens], [r for _, r in tokens])], None
    raw = _normalized_tokens(source)
    buckets: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for text, row in raw:
        container = container_of_row(units, row)
        buckets[container.unit_id].append((text, row))
    return [NgramStream(file_id, unit_id, [t for t, _ in pairs], [r for _, r in pairs]) for unit_id, pairs in buckets.items()], units


def cluster_evidence(file_sources: list[dict[str, str]], k: int = DEFAULT_K, min_run: int = DEFAULT_MIN_RUN) -> dict[str, Any]:
    """file_sources: [{"file_id": ..., "source_code": ...}] -> evidence dict.

    Returns:
      {signal, k, min_run, per_file_tokens: {file_id: n}, runs: [run...],
       pairs: [{file_a, file_b, shared_tokens, n_runs, tokens_a, tokens_b,
                containment, lines_a, lines_b, unit_pairs: [...]}],
       unit_tokens: {file_id: {unit_id: n}}, unit_pairs: [...],
       shared_units: [{name, files: [...], shared_tokens}]}
    """
    streams: list[NgramStream] = []
    per_file_tokens: dict[str, int] = {}
    unit_tokens: dict[str, dict[str, int]] = defaultdict(dict)
    unit_share_tokens: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for entry in file_sources:
        file_id = entry["file_id"]
        unit_streams, _ = _unit_streams(file_id, entry["source_code"])
        streams.extend(unit_streams)
        per_file_tokens[file_id] = sum(len(s.tokens) for s in unit_streams)
        unit_tokens[file_id] = {stream.unit_id: len(stream.tokens) for stream in unit_streams}

    runs = find_shared_runs(streams, k=k, min_run=min_run)

    pair_units: dict[tuple[str, str], dict[tuple[str, str], dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"shared_tokens": 0, "n_runs": 0})
    )
    runs_by_pair: dict[tuple[str, str], list[SharedRun]] = defaultdict(list)
    for run in runs:
        if run.file_a < run.file_b:
            file_a, unit_a, file_b, unit_b = run.file_a, run.unit_a, run.file_b, run.unit_b
        else:
            file_a, unit_a, file_b, unit_b = run.file_b, run.unit_b, run.file_a, run.unit_a
        runs_by_pair[(file_a, file_b)].append(run)
        pair_units[(file_a, file_b)][(unit_a, unit_b)]["shared_tokens"] += run.tokens
        pair_units[(file_a, file_b)][(unit_a, unit_b)]["n_runs"] += 1
        for run_file, run_unit in ((run.file_a, run.unit_a), (run.file_b, run.unit_b)):
            name = run_unit.split(":", 1)[1] if ":" in run_unit else run_unit
            if name not in {"module", "<module>"}:
                unit_share_tokens[name][run_file] += run.tokens

    pairs: list[dict[str, Any]] = []
    for (file_a, file_b), unit_evidence in pair_units.items():
        shared_tokens = sum(item["shared_tokens"] for item in unit_evidence.values())
        tokens_a, tokens_b = per_file_tokens.get(file_a, 0), per_file_tokens.get(file_b, 0)
        denom = max(min(tokens_a, tokens_b), 1)
        a_runs = runs_by_pair[(file_a, file_b)]
        lines_a = max((r.rows_a[1] for r in a_runs), default=0) - min((r.rows_a[0] for r in a_runs), default=0) + 1
        lines_b = max((r.rows_b[1] for r in a_runs), default=0) - min((r.rows_b[0] for r in a_runs), default=0) + 1
        pairs.append({
            "file_a": file_a,
            "file_b": file_b,
            "shared_tokens": shared_tokens,
            "n_runs": len(a_runs),
            "tokens_a": tokens_a,
            "tokens_b": tokens_b,
            "containment": round(shared_tokens / denom, 4),
            "lines_a": max(lines_a, 0),
            "lines_b": max(lines_b, 0),
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
    shared_units = [
        {"name": name, "files": sorted(files), "shared_tokens": sum(files.values())}
        for name, files in unit_share_tokens.items()
        if len(files) >= 2
    ]
    shared_units.sort(key=lambda item: item["shared_tokens"], reverse=True)

    return {
        "signal": "clone",
        "k": k,
        "min_run": min_run,
        "per_file_tokens": per_file_tokens,
        "unit_tokens": dict(unit_tokens),
        "pairs": pairs,
        "unit_pairs": [item for pair in pairs for item in pair["unit_pairs"]],
        "shared_units": shared_units,
    }
