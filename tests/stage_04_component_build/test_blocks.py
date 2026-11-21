"""Atomic block selection and prerequisite checks."""

from pathlib import Path

import pytest

from component_method.workflow.blocks import (
    BLOCK_GROUPS,
    block_status,
    publish_mode,
    resolve_block,
    resolve_blocks,
    selected_from_config,
    step_enabled,
)


def test_retired_stages_resolve_to_their_merged_block():
    assert resolve_block("source_scan").name == "prepare"
    assert resolve_block("extract").name == "build"
    assert resolve_block("curate").name == "build"
    assert resolve_block("prepare_reviews").name == "build"
    assert resolve_block("review").name == "audit"
    assert resolve_block("finalize_review").name == "audit"
    assert resolve_block("publish_library").name == "publish"
    assert resolve_block("retrieval").name == "retrieval"
    assert resolve_block("task").name == "task"


def test_block_selection_is_deduplicated_and_supports_all():
    assert resolve_blocks("extract,curate,review") == ("build", "audit")
    assert resolve_blocks("all") == (
        "prepare",
        "build",
        "audit",
        "publish",
        "retrieval",
        "task",
    )
    assert resolve_blocks(None) == resolve_blocks("all")


def test_deliver_group_expands_to_retrieval_and_task():
    assert BLOCK_GROUPS["deliver"] == ("retrieval", "task")
    assert resolve_blocks("deliver") == ("retrieval", "task")
    assert resolve_blocks("build,deliver") == ("build", "retrieval", "task")
    with pytest.raises(ValueError):
        resolve_block("deliver")


def test_config_blocks_override_the_default():
    assert selected_from_config({"blocks": ["prepare", "build"]}) == ("prepare", "build")
    assert selected_from_config(
        {"blocks": ["prepare", "build"]}, override="deliver"
    ) == ("retrieval", "task")


def test_block_status_is_decided_only_by_artifacts(tmp_path):
    task_root = Path(tmp_path)
    config = {"task_id": "task-a"}
    status = block_status("build", task_root, config)
    assert status["status"] == "blocked"
    assert status["missing"][0]["artifact"] == "packets"

    packets = task_root / "inputs" / "focus_context_packets.json"
    packets.parent.mkdir(parents=True)
    packets.write_text("{}", encoding="utf-8")
    status = block_status("build", task_root, config)
    assert status["ready"] is True
    assert status["completed"] is False

    frozen = task_root / "inputs" / "frozen_components.json"
    frozen.write_text("{}", encoding="utf-8")
    assert block_status("build", task_root, config)["status"] == "completed"


def test_publish_requirements_follow_mode(tmp_path):
    task_root = Path(tmp_path)
    frozen = task_root / "inputs" / "frozen_components.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_text("{}", encoding="utf-8")

    unreviewed = {"task_id": "task-a", "publish_mode": "unreviewed"}
    assert publish_mode(unreviewed) == "unreviewed"
    assert block_status("publish", task_root, unreviewed)["ready"] is True

    reviewed = {"task_id": "task-a"}
    assert block_status("publish", task_root, reviewed)["ready"] is False
    review = task_root / "runs" / "task-a" / "review_v1" / "summary.json"
    review.parent.mkdir(parents=True)
    review.write_text("{}", encoding="utf-8")
    assert block_status("publish", task_root, reviewed)["ready"] is True


def test_finalize_review_step_is_configuration_driven():
    assert step_enabled("finalize_review", {}) is False
    assert step_enabled("finalize_review", {"apply_review_revisions_without_rereview": True}) is True


def test_task_requires_the_retrieval_artifact(tmp_path):
    task_root = Path(tmp_path)
    config = {"task_id": "task-a"}
    library = task_root / "outputs" / "full_library" / "manifest.json"
    library.parent.mkdir(parents=True)
    library.write_text("{}", encoding="utf-8")

    assert block_status("retrieval", task_root, config)["ready"] is True
    assert block_status("task", task_root, config)["ready"] is False

    result = task_root / "attempts" / "retrieval_v1" / "result.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}", encoding="utf-8")
    assert block_status("task", task_root, config)["ready"] is True


def test_unknown_block_is_rejected():
    with pytest.raises(ValueError):
        resolve_block("not-a-block")