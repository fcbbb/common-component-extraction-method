from __future__ import annotations

import json
from pathlib import Path

from migration_scenario_validation.tools import migration_trial


def test_bundle_state_rejects_missing_and_empty_bundles(tmp_path):
    bundle = tmp_path / "component_bundle"
    missing = migration_trial._bundle_state(bundle)
    assert missing == {
        "ok": False,
        "reason": "missing",
        "path": str(bundle),
        "files": 0,
        "bytes": 0,
    }

    bundle.mkdir()
    assert migration_trial._bundle_state(bundle)["reason"] == "empty"

    (bundle / "INDEX.md").write_text("# bundle\n", encoding="utf-8")
    state = migration_trial._bundle_state(bundle)
    assert state["ok"] is True
    assert state["reason"] == ""
    assert state["files"] == 1
    assert state["component_count"] is None


def test_bundle_state_reads_component_count(tmp_path):
    bundle = tmp_path / "component_bundle"
    (bundle / "components" / "alpha").mkdir(parents=True)
    (bundle / "components" / "alpha" / "README.md").write_text("alpha\n", encoding="utf-8")
    (bundle / "manifest.json").write_text(
        json.dumps({"component_count": 3}), encoding="utf-8"
    )
    state = migration_trial._bundle_state(bundle)
    assert state["ok"] is True
    assert state["files"] == 2
    assert state["component_count"] == 3


def test_bundle_state_tolerates_a_broken_manifest(tmp_path):
    bundle = tmp_path / "component_bundle"
    bundle.mkdir()
    (bundle / "data.txt").write_text("x\n", encoding="utf-8")
    (bundle / "manifest.json").write_text("{not json", encoding="utf-8")
    state = migration_trial._bundle_state(bundle)
    assert state["ok"] is True
    assert state["component_count"] is None


def test_validated_empty_selection_is_a_legitimate_abstention(tmp_path):
    bundle = tmp_path / "component_bundle"
    bundle.mkdir()
    (bundle / "INDEX.md").write_text(
        "# Selected component paths\n\n0 methodology components selected.\n",
        encoding="utf-8",
    )
    (bundle / "manifest.json").write_text(
        json.dumps({"component_count": 0}), encoding="utf-8"
    )
    state = migration_trial._bundle_state(bundle)
    assert state["ok"] is True
    assert state["component_count"] == 0
    assert migration_trial._validated_empty_selection(state) is True


def test_empty_selection_needs_a_manifest_and_zero_count(tmp_path):
    bundle = tmp_path / "component_bundle"
    bundle.mkdir()
    (bundle / "INDEX.md").write_text("# bundle\n", encoding="utf-8")
    # Files exist but no manifest: not a validated zero-component selection.
    assert migration_trial._validated_empty_selection(
        migration_trial._bundle_state(bundle)
    ) is False

    (bundle / "manifest.json").write_text(
        json.dumps({"component_count": 2}), encoding="utf-8"
    )
    assert migration_trial._validated_empty_selection(
        migration_trial._bundle_state(bundle)
    ) is False


def test_image_identity_records_the_immutable_id(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return 0, json.dumps([
            {
                "Id": "sha256:abc",
                "RepoDigests": ["migration/ipp@sha256:def"],
                "Created": "2026-11-17T00:00:00Z",
                "Unrelated": "ignored",
            }
        ])

    monkeypatch.setattr(migration_trial.at, "_run", fake_run)
    migration_trial._IMAGE_IDENTITY_CACHE.clear()
    first = migration_trial._image_identity("migration/test-identity:cpu")
    second = migration_trial._image_identity("migration/test-identity:cpu")
    assert first == second == {
        "image": "migration/test-identity:cpu",
        "id": "sha256:abc",
        "repo_digests": ["migration/ipp@sha256:def"],
        "created": "2026-11-17T00:00:00Z",
    }
    assert len(calls) == 1


def test_method_stage_usage_reads_extraction_and_retrieval(tmp_path):
    task_root = tmp_path / "method-task"
    extraction = task_root / "runs" / "task-a" / "extraction_v1"
    retrieval = task_root / "attempts" / "retrieval_v1"
    extraction.mkdir(parents=True)
    retrieval.mkdir(parents=True)
    (task_root / "config.json").write_text(
        json.dumps({"task_id": "task-a", "retrieval_attempt": "retrieval_v1"}),
        encoding="utf-8",
    )
    (extraction / "summary.json").write_text(
        json.dumps({
            "successful_packets": 4,
            "invalid_packets": 0,
            "failed_packets": 0,
            "component_count": 7,
            "extraction_api_calls": 9,
            "extraction_input_tokens": 900,
            "extraction_output_tokens": 90,
            "extraction_reported_cost_usd": 0.5,
            "ignored": "value",
        }),
        encoding="utf-8",
    )
    (retrieval / "metadata.json").write_text(
        json.dumps({
            "model_calls": 12,
            "input_tokens": 1000,
            "output_tokens": 200,
            "reported_cost_usd": 0.25,
            "status": "Submitted",
        }),
        encoding="utf-8",
    )
    assert migration_trial._method_stage_usage(str(task_root)) == {
        "extraction": {
            "successful_packets": 4,
            "invalid_packets": 0,
            "failed_packets": 0,
            "component_count": 7,
            "extraction_api_calls": 9,
            "extraction_input_tokens": 900,
            "extraction_output_tokens": 90,
            "extraction_reported_cost_usd": 0.5,
        },
        "retrieval": {
            "model_calls": 12,
            "input_tokens": 1000,
            "output_tokens": 200,
            "reported_cost_usd": 0.25,
        },
    }


def test_tool_call_counts_separate_workflow_from_migration():
    counts = migration_trial._tool_call_counts([
        {"tool": "component_source_scan"},
        {"tool": "controlled_bash"},
        {"tool": "component_extract"},
        {"tool": "controlled_bash"},
        {},
    ])
    assert counts == {
        "component_source_scan": 1,
        "component_extract": 1,
        "controlled_bash": 2,
        "unknown": 1,
    }