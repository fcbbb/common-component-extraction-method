from copy import deepcopy
import gzip
import json

import numpy as np
import pytest

pytest.importorskip("clang.cindex")
pytest.importorskip("tree_sitter_java")
pytest.importorskip("hnswlib")

from component_method.component_build.pipeline import build_artifact_library
from component_method.protocol_candidates import build_candidates
from component_method.protocol_candidates.extraction import pack_protocol_candidates
from component_method.signal_analysis import fusion
from component_method.signal_analysis.prepare_embeddings import prepare_corpus
from test_artifact_pipeline import fixture_component, fake_executor


def test_real_mixed_language_scan_candidates_and_packet_partition(tmp_path, monkeypatch):
    root = tmp_path / "snapshot"
    root.mkdir()
    sources = {
        "left.py": "def calculate(value):\n    return value + 1\n",
        "right.py": "def increment(value):\n    return value + 1\n",
        "left.cpp": "int calculate(int value) { return value + 1; }\n",
        "right.cpp": "int increment(int value) { return value + 1; }\n",
        "Left.java": "public class Left { public static int calculate(int value) { return value + 1; } }\n",
        "Right.java": "public class Right { public static int increment(int value) { return value + 1; } }\n",
    }
    for path, content in sources.items():
        (root / path).write_text(content)
    task = {"instance_id": "mixed", "repository_root": "snapshot", "source_subdir": ".", "cohort": "fixture",
            "repo": "fixture/mixed", "base_commit": "a" * 40,
            "languages": [{"id": "java"}, {"id": "python"}, {"id": "cpp"}]}
    config = {"experiment_id": "mixed", "embedding": {"model_id": "fixture", "model_revision": "fixed",
                                                            "max_seq_length": 32, "batch_size": 2}}
    manifest = prepare_corpus([task], config, tmp_path / "embeddings", tmp_path)
    with gzip.open(tmp_path / "embeddings/units.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    monkeypatch.setattr(build_candidates, "PROJECT", tmp_path)
    monkeypatch.setattr(build_candidates, "ROOT", tmp_path / "work")
    cfg = {"semantic_top_k": 1, "strict_fusion": deepcopy(fusion.DEFAULT_CFG),
           "protocol_recall": {"semantic_seed_min_cosine": 0.5}}
    matrix = np.full((len(rows), 4), 0.5, dtype=np.float32)
    build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=False, reuse_frozen=False)
    candidates = json.loads((tmp_path / "work/tasks/mixed/candidates/protocol_candidates_v2.json").read_text())
    assert {p["language"] for p in candidates["partitions"]} == {"python", "cpp", "java"}
    by_key = {row["unit_key"]: row["language"] for row in rows}
    for candidate in candidates["candidates"]:
        assert {by_key[u["unit_id"]] for u in candidate["units"]} == {candidate["language"]}
        assert all(u["unit_key"] == u["unit_id"] for u in candidate["units"])
    packets = pack_protocol_candidates(candidates["candidates"])
    assert {p["language"] for p in packets} == {"python", "cpp", "java"}
    assert all({by_key[u["unit_id"]] for u in p["primary_units"]} == {p["language"]} for p in packets)
    # Reordering configured backends cannot change the corpus or graph.
    task["languages"].reverse()
    again = prepare_corpus([task], config, tmp_path / "again", tmp_path)
    assert again["unit_order_sha256"] == manifest["unit_order_sha256"]


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
def test_same_orchestration_for_each_language(language, tmp_path):
    component, review, repository = fixture_component(tmp_path, language)
    class FixtureAgent:
        def run_workspace_agent(self, **kwargs):
            if kwargs.get("agent_role") == "review":
                return deepcopy(review)
            return {"status": "ready", "components": [deepcopy(component)],
                    "workspace_audit": {"checked_files": [m["file_id"] for m in component["members"]], "gaps": []}}
    packet = {"packet_id": "packet", "language": language, "backend_id": language + "@1",
              "primary_files": [m["file_id"] for m in component["members"]], "primary_units": component["members"]}
    result = build_artifact_library(packets=[packet], repository=repository, agent_runner=FixtureAgent(),
                                     output_dir=tmp_path / "pipeline", executor=fake_executor)
    assert result["published_count"] == 1, result
    assert result["results"][0]["language"] == language
