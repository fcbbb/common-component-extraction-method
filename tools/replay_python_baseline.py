#!/usr/bin/env python3
"""Replay the small frozen Python corpus without Docker, models, or embeddings."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from component_method.component_build.contracts import normalize_component_draft
from component_method.protocol_candidates.extraction import pack_protocol_candidates
from component_method.protocol_candidates.protocol_recall import recall_candidates
from component_method.signal_analysis.ast_signal import cluster_evidence as skeleton
from component_method.signal_analysis.clone_signal import cluster_evidence as clone
from component_method.source_scan.unit_extraction import extract_unit_sources
from component_method.source_scan.units import source_unit_records

FIXTURE = REPOSITORY / "tests/fixtures/multilanguage/python_baseline.json"


def replay(fixture: dict) -> dict:
    sources = fixture["sources"]
    signals = [clone(sources), skeleton(sources), fixture["semantic"]]
    candidates = recall_candidates(sources, signals, {"top_candidates": 5})
    stages = {
        "embedding_units": extract_unit_sources(sources),
        "source_records": {row["file_id"]: source_unit_records(row["source_code"]) for row in sources},
        "clone": signals[0],
        "skeleton": signals[1],
        "semantic": signals[2],
        "candidates": candidates,
        "packets": pack_protocol_candidates(candidates["candidates"]),
        "component": normalize_component_draft(
            fixture["component"], component_id="baseline", origin_strategy="baseline"
        ).to_json(),
    }
    return {
        "schema": "python-characterization-baseline-v1",
        "ordering": "input files; legacy backend order within each stage; candidate rank",
        "source_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    actual = replay(fixture)
    expected = fixture["expected"]
    if actual != expected:
        print("".join(difflib.unified_diff(
            json.dumps(expected, sort_keys=True, indent=2).splitlines(keepends=True),
            json.dumps(actual, sort_keys=True, indent=2).splitlines(keepends=True),
            fromfile="frozen", tofile="replayed",
        )))
        return 1
    print(f"Python baseline matches: {len(actual['stages'])} stages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
