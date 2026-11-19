from __future__ import annotations

import json
from pathlib import Path

import pytest

from migration_scenario_validation.tools import origin_trial


def test_origin_applies_text_files_and_deletes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "old.c").write_text("old\n", encoding="utf-8")
    written = origin_trial.apply_response(
        workspace,
        json.dumps(
            {
                "files": [{"path": "src/new.c", "content": "int x;\n"}],
                "delete": ["old.c"],
            }
        ),
    )
    assert (workspace / "src" / "new.c").read_text() == "int x;\n"
    assert not (workspace / "old.c").exists()
    assert written == ["src/new.c", "DELETE old.c"]


def test_origin_rejects_workspace_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError):
        origin_trial.apply_response(
            workspace,
            json.dumps({"files": [{"path": "../escape.c", "content": "x"}]}),
        )


def test_origin_context_includes_metadata_files(tmp_path):
    task_root = tmp_path / "task"
    work = task_root / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (work / "CMakeLists.txt").write_text("project(x)\n", encoding="utf-8")
    task = {
        "task_id": "x",
        "scenario": "ipp_to_vsipl",
        "level": "L1",
        "spec": "migrate main",
        "source": {"files": ["src/main.c"]},
        "build": {"command": "cmake -S . -B build"},
    }
    ctx = origin_trial.build_context(task_root, task, 100_000)
    assert "src/main.c" in ctx["included"]
    assert "int main(void)" in ctx["prompt"]
    assert "## OUTPUT CONTRACT" in ctx["prompt"]
