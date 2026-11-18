from __future__ import annotations

import json
from pathlib import Path

import pytest

from component_method.source_scan.prepare_migration_inputs import (
    build_inputs,
    verify_workspace_unchanged,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "alpha.py").write_text(
        "def alpha(x):\n    return x + 1\n", encoding="utf-8"
    )
    (workspace / "src" / "beta.py").write_text(
        "class Beta:\n    def run(self):\n        return 2\n", encoding="utf-8"
    )
    (workspace / "src" / "test_alpha.py").write_text(
        "def test_alpha():\n    assert True\n", encoding="utf-8"
    )
    (workspace / "vendor" / "ignored.py").parent.mkdir(parents=True)
    (workspace / "vendor" / "ignored.py").write_text("def vendored():\n    pass\n", encoding="utf-8")
    return workspace


def _config(workspace: Path, **overrides) -> dict:
    config = {
        "task_id": "task-a",
        "repository_root": str(workspace),
        "source_scan_mode": "migration",
        "language": "python",
        "backend_id": "python@1",
        "packet_config": {
            "extensions": [".py"],
            "max_files_per_packet": 1,
            "max_units_per_packet": 200,
        },
    }
    config.update(overrides)
    return config


def test_build_inputs_partitions_the_migration_workspace(tmp_path):
    workspace = _workspace(tmp_path)
    task_root = tmp_path / "method-task"

    payload = build_inputs(_config(workspace), task_root=task_root)

    output = task_root / "inputs" / "focus_context_packets.json"
    assert json.loads(output.read_text()) == payload
    assert payload["schema"] == "migration-focus-context-packets-v1"
    assert payload["task_blind"] is True
    assert payload["task_information_used"] is False
    assert payload["scenario"] == ""
    assert payload["language"] == "python"
    assert payload["backend_id"] == "python@1"
    assert payload["source_file_count"] == 2
    assert payload["source_unit_count"] == 3
    assert payload["packet_count"] == 2
    assert payload["gaps"] == []

    packets = payload["packets"]
    assert [packet["packet_id"] for packet in packets] == ["region_001", "region_002"]
    assert [packet["visible_files"] for packet in packets] == [
        ["src/alpha.py"],
        ["src/beta.py"],
    ]
    assert [packet["focus_unit_count"] for packet in packets] == [1, 2]
    assert packets[0]["focus_groups"][0]["seed_evidence"] == [
        {"file_id": "src/alpha.py", "line_start": 1, "line_end": 2}
    ]


def test_build_inputs_is_idempotent_for_an_unchanged_workspace(tmp_path):
    workspace = _workspace(tmp_path)
    task_root = tmp_path / "method-task"
    first = build_inputs(_config(workspace), task_root=task_root)
    second = build_inputs(_config(workspace), task_root=task_root)
    assert first == second


def test_verify_workspace_unchanged_accepts_the_frozen_tree(tmp_path):
    workspace = _workspace(tmp_path)
    config = _config(workspace)
    payload = build_inputs(config, task_root=tmp_path / "method-task")
    verify_workspace_unchanged(config, payload)


def test_verify_workspace_unchanged_detects_edits_and_new_files(tmp_path):
    workspace = _workspace(tmp_path)
    config = _config(workspace)
    payload = build_inputs(config, task_root=tmp_path / "method-task")

    (workspace / "src" / "alpha.py").write_text(
        "def alpha(x):\n    return x + 2\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="workspace changed after source_scan"):
        verify_workspace_unchanged(config, payload)

    (workspace / "src" / "alpha.py").write_text(
        "def alpha(x):\n    return x + 1\n", encoding="utf-8"
    )
    (workspace / "src" / "gamma.py").write_text(
        "def gamma():\n    return 3\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="added="):
        verify_workspace_unchanged(config, payload)


def test_build_inputs_refuses_to_replace_a_different_frozen_input(tmp_path):
    workspace = _workspace(tmp_path)
    task_root = tmp_path / "method-task"
    build_inputs(_config(workspace), task_root=task_root)
    (workspace / "src" / "alpha.py").write_text(
        "def alpha(x):\n    return x + 2\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="preserving different frozen input"):
        build_inputs(_config(workspace), task_root=task_root)


def test_build_inputs_rejects_a_backend_identity_mismatch(tmp_path):
    workspace = _workspace(tmp_path)
    with pytest.raises(RuntimeError, match="backend identity"):
        build_inputs(
            _config(workspace, backend_id="cpp@1"),
            task_root=tmp_path / "method-task",
        )


def test_build_inputs_fails_when_no_source_units_parse(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "build").mkdir(parents=True)
    (workspace / "build" / "skip.py").write_text("def f():\n    pass\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no extractable source units"):
        build_inputs(_config(workspace), task_root=tmp_path / "method-task")