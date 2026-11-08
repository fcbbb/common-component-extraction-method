from copy import deepcopy
import gzip
import json

import numpy as np
import pytest

from component_method.languages.contracts import BackendIdentity, SourceUnit, Span, stable_digest
from component_method.languages.registry import LanguageRegistry
from component_method.languages.python.backend import PythonBackend
from component_method.signal_analysis.compute_embeddings import (
    completed_output_matches, load_reuse, reuse_backend_matches,
)
from component_method.signal_analysis.prepare_embeddings import eligible_files, prepare_corpus
from component_method.workflow.batch_common import sha256_file
from tools.replay_python_baseline import FIXTURE


def corpus(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for row in fixture["sources"]:
        (snapshot / row["file_id"]).write_text(row["source_code"], encoding="utf-8")
    task = {"instance_id": "test", "repository_root": "snapshot", "source_subdir": ".",
            "cohort": "test", "repo": "test/repo", "base_commit": "frozen"}
    config = {"experiment_id": "test", "embedding": {
        "model_id": "fixture", "model_revision": "fixed", "max_seq_length": 10, "batch_size": 2,
    }}
    return fixture, snapshot, task, config


def read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def test_v2_corpus_preserves_legacy_units_and_is_reproducible(tmp_path):
    fixture, _, task, cfg = corpus(tmp_path)
    output = tmp_path / "embeddings"
    first = prepare_corpus([task], cfg, output, tmp_path)
    data = (output / "units.jsonl.gz").read_bytes()
    rows = read_rows(output / "units.jsonl.gz")
    assert first["schema"] == "featurebench-c2llm-offline-input-v2"
    assert [{key: row[key] for key in ("file_id", "unit_id", "source_code")} for row in rows] == fixture["expected"]["stages"]["embedding_units"]
    assert all(row["schema"] == "source-unit-v2" and row["backend_id"] == "python@1" for row in rows)
    assert first["language_backends"]["test"]["backends"][0] == PythonBackend().identity().to_json()
    assert first == prepare_corpus([task], cfg, output, tmp_path)
    assert data == (output / "units.jsonl.gz").read_bytes()


def test_scanner_preserves_parent_first_order_and_filters(tmp_path):
    _, snapshot, task, cfg = corpus(tmp_path)
    (snapshot / "nested").mkdir()
    (snapshot / "nested/a.py").write_text("VALUE = 1\n")
    (snapshot / "test_ignored.py").write_text("VALUE = 1\n")
    files = [file_id for _, file_id in eligible_files(snapshot, ".")]
    assert files == ["alpha.py", "beta.py", "broken.py", "nested/a.py"]
    task["languages"] = [{"id": "python", "include": ["**/*.py"], "exclude": ["nested/**"]}]
    output = tmp_path / "embeddings"
    prepare_corpus([task], cfg, output, tmp_path)
    assert {row["file_id"] for row in read_rows(output / "units.jsonl.gz")} == set(files[:3])


def test_v2_prepare_does_not_overwrite_legacy_inputs(tmp_path):
    _, _, task, cfg = corpus(tmp_path)
    output = tmp_path / "embeddings"
    output.mkdir()
    old = '{"schema":"featurebench-c2llm-offline-input-v1"}'
    (output / "input_manifest.json").write_text(old)
    with pytest.raises(RuntimeError, match="preserving legacy"):
        prepare_corpus([task], cfg, output, tmp_path)
    assert (output / "input_manifest.json").read_text() == old
    assert not (output / "units.jsonl.gz").exists()


def test_reuse_is_partitioned_by_backend_identity():
    old = {"schema": "featurebench-c2llm-offline-input-v2", "language_backends": {"one": {"identity": "original"}}}
    same = deepcopy(old)
    same["language_backends"]["two"] = {"identity": "another"}
    assert reuse_backend_matches(old, same, "one")
    changed = deepcopy(old)
    changed["language_backends"]["one"]["identity"] = "changed"
    assert not reuse_backend_matches(old, changed, "one")
    assert not reuse_backend_matches(old, same, "two")
    legacy = {"schema": "featurebench-c2llm-offline-input-v1"}
    assert not reuse_backend_matches(legacy, same, "one")
    assert reuse_backend_matches(legacy, legacy, "one")


def test_load_reuse_skips_rows_from_changed_backends(tmp_path):
    _, _, task, cfg = corpus(tmp_path)
    output = tmp_path / "embeddings"
    manifest = prepare_corpus([task], cfg, output, tmp_path)
    np.save(output / "unit_embeddings.npy", np.zeros((manifest["unit_count"], 2), dtype=np.float32))
    result = {"input_manifest_sha256": sha256_file(output / "input_manifest.json"),
              "units_file_sha256": sha256_file(output / "units.jsonl.gz"),
              "embedding_file_sha256": sha256_file(output / "unit_embeddings.npy"),
              "embedding_shape": [manifest["unit_count"], 2]}
    (output / "embedding_result_manifest.json").write_text(json.dumps(result))
    assert load_reuse(output, manifest)[3]
    changed = deepcopy(manifest)
    changed["language_backends"]["test"]["path_rules_sha256"] = stable_digest("changed")
    assert not load_reuse(output, changed)[3]


def test_completed_embedding_checks_inputs_before_resume(tmp_path):
    input_path, manifest_path, output_path = [tmp_path / name for name in ("units", "manifest", "vectors")]
    for path in (input_path, manifest_path, output_path):
        path.write_text(path.name)
    manifest = {"unit_order_sha256": "order"}
    result = {"input_manifest_sha256": sha256_file(manifest_path), "units_file_sha256": sha256_file(input_path),
              "embedding_file_sha256": sha256_file(output_path), "unit_order_sha256": "order"}
    assert completed_output_matches(result, manifest, input_path, manifest_path, output_path)
    manifest_path.write_text("changed backend identity")
    assert not completed_output_matches(result, manifest, input_path, manifest_path, output_path)


def test_scanning_fans_out_without_language_specific_core_rules(tmp_path):
    _, snapshot, task, cfg = corpus(tmp_path)

    class FixtureBackend:
        def __init__(self, language_id):
            self.language_id = language_id
            self.backend_id = f"{language_id}@1"

        def identity(self):
            return BackendIdentity(self.language_id, "1", "fixture", "1", "0" * 64)

        def eligible_files(self, root, source_subdir):
            return [root / self.language_id]

        def extract_units(self, file_id, source):
            return [SourceUnit(self.language_id, self.backend_id, file_id, "function", "opaque",
                               "opaque", None, "signature", Span(1, 1), source)]

        def scan_policy(self):
            return {"fixture": self.language_id}

    for name in ("a", "z"):
        (snapshot / name).write_text("input with no Python syntax")
    registry = LanguageRegistry()
    for name in ("z", "a"):
        registry.register(FixtureBackend(name))
    cfg["languages"] = [{"id": "z"}, {"id": "a"}]
    output = tmp_path / "embeddings"
    manifest = prepare_corpus([task], cfg, output, tmp_path, registry=registry)
    rows = read_rows(output / "units.jsonl.gz")
    assert [row["language"] for row in rows] == ["a", "z"]
    assert len({row["unit_key"] for row in rows}) == 2
    assert [backend["language"] for backend in manifest["language_backends"]["test"]["backends"]] == ["a", "z"]
