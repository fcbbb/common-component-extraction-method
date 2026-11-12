from copy import deepcopy
import gzip
import hashlib
import json

import numpy as np
import pytest

pytest.importorskip("hnswlib")

from component_method.protocol_candidates import build_candidates
from component_method.languages.python.backend import PythonBackend
from component_method.signal_analysis import fusion
from component_method.signal_analysis.prepare_embeddings import prepare_corpus
from component_method.workflow.batch_common import sha256_file
from tools.replay_python_baseline import FIXTURE


def setup_pipeline(tmp_path, monkeypatch):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for entry in fixture["sources"]:
        (snapshot / entry["file_id"]).write_text(entry["source_code"], encoding="utf-8")
    task = {"instance_id": "fixture", "repository_root": "snapshot", "source_subdir": ".",
            "cohort": "test", "repo": "fixture/repo", "base_commit": "frozen"}
    config = {"experiment_id": "fixture", "embedding": {
        "model_id": "fixture", "model_revision": "fixed", "max_seq_length": 10, "batch_size": 2,
    }}
    output = tmp_path / "embeddings"
    manifest = prepare_corpus([task], config, output, tmp_path)
    with gzip.open(output / "units.jsonl.gz", "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    matrix = np.full((len(rows), 4), 0.5, dtype=np.float32)
    result = {
        "input_manifest_sha256": sha256_file(output / "input_manifest.json"),
        "units_file_sha256": sha256_file(output / "units.jsonl.gz"),
        "embedding_shape": list(matrix.shape), "unit_order_sha256": manifest["unit_order_sha256"],
    }
    np.save(output / "unit_embeddings.npy", matrix)
    result["embedding_file_sha256"] = sha256_file(output / "unit_embeddings.npy")
    (output / "embedding_result_manifest.json").write_text(json.dumps(result))
    monkeypatch.setattr(build_candidates, "PROJECT", tmp_path)
    monkeypatch.setattr(build_candidates, "ROOT", tmp_path / "work")
    candidate_config = {"semantic_top_k": 2, "strict_fusion": deepcopy(fusion.DEFAULT_CFG),
                        "protocol_recall": {"top_candidates": 5}}
    return fixture, task, manifest, rows, matrix, candidate_config, output


def test_v2_embedding_to_candidates_and_resume(tmp_path, monkeypatch):
    fixture, task, manifest, rows, matrix, cfg, output = setup_pipeline(tmp_path, monkeypatch)
    validated = build_candidates.validate_matrix(output)
    assert validated[0] == manifest
    assert validated[2] == rows
    build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=False, reuse_frozen=False)
    root = tmp_path / "work/tasks/fixture"
    for signal in ("clone", "skeleton"):
        assert json.loads((root / f"signals/{signal}.json").read_text()) == fixture["expected"]["stages"][signal]
    status_path = root / "candidates/status.json"
    status = json.loads(status_path.read_text())
    assert status["protocol_candidates"] > 0
    assert status["language_backends"] == manifest["language_backends"]["fixture"]
    assert not status["legacy_embedding_input"]
    packet_path = root / "candidates/protocol_packets_v2.json"
    packet_manifest = json.loads(packet_path.read_text())
    assert packet_manifest["schema"] == "protocol-packets-v2"
    assert packet_manifest["candidate_count"] == status["protocol_candidates"]
    assert packet_manifest["packet_count"] == status["protocol_packets"]
    assert len(packet_manifest["packets"]) == packet_manifest["packet_count"]
    assert sum(len(p["candidate_ids"]) for p in packet_manifest["packets"]) == packet_manifest["candidate_count"]
    before = status_path.read_bytes()
    build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=True, reuse_frozen=False)
    assert status_path.read_bytes() == before

    # Changing vectors must invalidate resume even when the source corpus is identical.
    matrix[0] = (1.0, 0.0, 0.0, 0.0)
    build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=True, reuse_frozen=False)
    assert json.loads(status_path.read_text())["input_fingerprint"] != status["input_fingerprint"]

    (tmp_path / "snapshot/alpha.py").write_text("def changed():\n    pass\n")
    with pytest.raises(RuntimeError, match="units changed"):
        build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=True, reuse_frozen=False)


def test_candidate_stage_rejects_changed_backend_manifest(tmp_path, monkeypatch):
    _, task, manifest, rows, matrix, cfg, _ = setup_pipeline(tmp_path, monkeypatch)
    manifest["language_backends"]["fixture"]["backends"][0]["implementation_sha256"] = "changed"
    with pytest.raises(RuntimeError, match="backend identity"):
        build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=True, reuse_frozen=False)
    assert not (tmp_path / "work").exists()


def test_candidate_validation_still_reads_frozen_v1_units(tmp_path, monkeypatch):
    _, task, _, rows, _, _, _ = setup_pipeline(tmp_path, monkeypatch)
    legacy_rows = [{key: row[key] for key in (
        "file_id", "unit_id", "unit_sha256", "source_code"
    )} for row in rows]
    sources, units = build_candidates.validate_units(task, legacy_rows)
    assert len(sources) == 3
    assert len(units) == len(rows)


def test_candidate_validation_rejects_coordinate_only_source_changes(tmp_path, monkeypatch):
    _, task, _, _, _, _, _ = setup_pipeline(tmp_path, monkeypatch)
    # Use a file with no residual module unit, so the callable text is identical.
    source = tmp_path / "snapshot/functions.py"
    source.write_text("def stable():\n    return 1\n")
    rows = []
    for entry in build_candidates.collect_sources(task):
        for unit in PythonBackend().extract_units(entry["file_id"], entry["source_code"]):
            rows.append({**unit.to_json(), "unit_id": unit.metadata["legacy_unit_id"],
                         "source_sha256": hashlib.sha256(entry["source_code"].encode()).hexdigest(),
                         "unit_sha256": hashlib.sha256(unit.source_code.encode()).hexdigest()})
    source.write_text("\n\ndef stable():\n    return 1\n")
    with pytest.raises(RuntimeError, match="source changed"):
        build_candidates.validate_units(task, rows)


def test_candidate_resume_tracks_frozen_copy_mode(tmp_path, monkeypatch):
    _, task, manifest, rows, matrix, cfg, _ = setup_pipeline(tmp_path, monkeypatch)
    frozen = tmp_path / "frozen.json"
    frozen.write_text('{"candidates": [], "stats": {}}')
    task["frozen_candidate"] = frozen.name
    build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=False, reuse_frozen=True)
    status_path = tmp_path / "work/tasks/fixture/candidates/status.json"
    copied = json.loads(status_path.read_text())
    assert copied["provenance"]["mode"] == "copied_frozen_v2_candidate"
    build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=True, reuse_frozen=False)
    generated = json.loads(status_path.read_text())
    assert generated["input_fingerprint"] != copied["input_fingerprint"]
    assert generated["protocol_candidates"] > 0


def test_changing_languages_requires_new_embedding_manifest(tmp_path, monkeypatch):
    _, task, manifest, rows, matrix, cfg, _ = setup_pipeline(tmp_path, monkeypatch)
    task["languages"] = [{"id": "python"}, {"id": "cpp"}]
    pytest.importorskip("clang.cindex")
    with pytest.raises(RuntimeError, match="backend identity"):
        build_candidates.build_task(task, cfg, manifest, rows, matrix, resume=False, reuse_frozen=False)
