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


def test_origin_context_does_not_expose_hidden_tests(tmp_path):
    task_root = tmp_path / "task"
    work = task_root / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = {
        "task_id": "x",
        "scenario": "ipp_to_vsipl",
        "level": "L1",
        "spec": "migrate main",
        "hidden_tests": {"cases": ["SECRET_HIDDEN_CASE"]},
        "gates": {"api_removal": {"symbol_regex": "SECRET_GATE"}},
        "source": {"files": ["src/main.c"]},
        "build": {"command": "true"},
    }
    ctx = origin_trial.build_context(task_root, task, 100_000)
    assert "SECRET_HIDDEN_CASE" not in ctx["prompt"]
    assert "SECRET_GATE" not in ctx["prompt"]


def test_origin_system_prompt_is_target_aware(tmp_path):
    ipp_task = {"task_id": "x", "scenario": "ipp_to_vsipl"}
    ipp = origin_trial.origin_system_prompt(ipp_task)
    assert "migrating a C/C++ component from Intel IPP to VSIPL (jvsip)" in ipp
    assert "must use the VSIPL C API and link against libvsip" in ipp
    assert "portable fallback is not accepted" in ipp

    kylin_task = {"task_id": "x", "scenario": "windows_to_kylin"}
    kylin = origin_trial.origin_system_prompt(kylin_task)
    assert "porting one component to Kylin V10 SP3" in kylin
    assert "target Kylin/Linux platform APIs" in kylin
    assert "portable Windows-independent fallback" in kylin


def test_origin_context_uses_target_aware_system(tmp_path):
    task_root = tmp_path / "task"
    work = task_root / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = {
        "task_id": "x",
        "scenario": "ipp_to_vsipl",
        "spec": "migrate main",
        "source": {"files": ["src/main.c"]},
        "build": {"command": "true"},
    }
    ctx = origin_trial.build_context(task_root, task, 100_000)
    assert "must use the VSIPL C API" in ctx["system"]
    assert "must use the VSIPL C API" in ctx["prompt"]


def test_origin_extract_json_allows_raw_control_characters():
    text = '{"files":[{"path":"a.c","content":"line1\nline2"}],"delete":[],"notes":""}'
    value = origin_trial._extract_json(text)
    assert value["files"][0]["content"] == "line1\nline2"


def test_origin_context_does_not_dump_entire_repository(tmp_path):
    task_root = tmp_path / "task"
    work = task_root / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (work / "CMakeLists.txt").write_text("project(x)\n", encoding="utf-8")
    (work / "docs").mkdir()
    (work / "docs" / "large.txt").write_text("UNRELATED\n" * 10000, encoding="utf-8")
    task = {
        "task_id": "x",
        "scenario": "ipp_to_vsipl",
        "spec": "migrate main",
        "source": {"files": ["src/main.c"]},
        "build": {"command": "cmake -S . -B build"},
    }
    ctx = origin_trial.build_context(task_root, task, 100_000)
    assert "src/main.c" in ctx["included"]
    assert "docs/large.txt" not in ctx["included"]
    assert "UNRELATED" not in ctx["prompt"]
