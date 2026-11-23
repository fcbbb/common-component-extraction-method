from __future__ import annotations

import json
from pathlib import Path

import pytest

from component_method.dsh_registry import load_registry, resolve_run
from migration_scenario_validation.tools import method_adapter


def _task_package(root: Path, *, task_id: str = "task-a", scenario: str = "ipp_to_vsipl") -> Path:
    root.mkdir(parents=True)
    (root / "work" / "src").mkdir(parents=True)
    (root / "work" / "src" / "main.c").write_text(
        "int add(int a, int b) { return a + b; }\n", encoding="utf-8"
    )
    (root / "task.yaml").write_text(
        "\n".join(
            [
                f"task_id: {task_id}",
                f"scenario: {scenario}",
                "level: L1",
                "source:",
                "  repo: https://example.invalid/repo.git",
                '  commit: "abc123"',
                "target:",
                "  api: VSIPL",
                "spec: migrate add()",
                "gates:",
                "  behavior: add must stay unchanged",
                "build:",
                "  command: make",
                "hidden_tests: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def test_build_workspace_registers_migration_task_for_preparation(tmp_path):
    task_root = _task_package(tmp_path / "task-a")
    output_root = tmp_path / "adapter"

    view = method_adapter.build_workspace(
        [task_root],
        output_root=output_root,
        run_id="demo/run",
        model="model-x",
        api_base="https://example.invalid/v1/",
        runtime_images={"ipp_to_vsipl": "migration/ipp:cpu"},
        extraction_workers=3,
        review_workers=1,
        agent_timeout=900,
    )

    assert view["schema"] == "migration-method-adapter-v2"
    assert view["run_id"] == "demo-run"
    assert view["library"] == str(output_root / "tasks" / "task-a" / "outputs" / "full_library")

    entry = view["tasks"]["task-a"]
    assert entry["migration_task_root"] == str(task_root)
    snapshot = output_root / "tasks" / "task-a" / "source_snapshot"
    assert entry["repository_root"] == str(snapshot)
    assert entry["task_workspace"] == str(task_root / "work")
    assert entry["bundle_destination"] == str(task_root / "work" / "component_bundle")

    registry = load_registry(Path(view["registry"]))
    resolved = resolve_run(registry, "demo-run", "task-a")
    assert resolved["task_root"] == output_root / "tasks" / "task-a"
    # Stage tools that take only run_id (curate, publish_library) resolve the
    # single task through the run default.
    assert resolve_run(registry, "demo-run")["task_root"] == output_root / "tasks" / "task-a"

    config = json.loads((output_root / "tasks" / "task-a" / "config.json").read_text())
    assert config["repository_root"] == str(snapshot)
    assert config["task_workspace"] == str(task_root / "work")
    assert config["source_scan_mode"] == "migration"
    assert "publish_mode" not in config
    assert config["max_review_repair_rounds"] == 1
    assert config["language"] == "cpp"
    assert config["backend_id"] == "cpp@1"
    assert config["extraction_workers"] == 3
    assert config["review_workers"] == 1
    assert config["agent_timeout_seconds"] == 900
    assert config["api_base"] == "https://example.invalid/v1"
    assert config["runtime_image"] == "migration/ipp:cpu"
    assert config["selection_path"] == entry["selection_path"]
    assert config["coverage_path"] == entry["coverage_path"]
    assert config["bundle_destination"] == entry["bundle_destination"]

    task_doc = json.loads((output_root / "tasks" / "task-a" / "task.json").read_text())
    assert task_doc["instance_id"] == "task-a"
    assert task_doc["problem_statement"].startswith("migrate add()")
    assert task_doc["interface"] == "Match the observable behavior in the task spec."
    assert task_doc["component_bundle"] == entry["bundle_destination"]
    assert (output_root / "offline_tasks" / "task-a" / "task.json").is_file()


def test_build_workspace_uses_musa_python_backend(tmp_path):
    task_root = _task_package(tmp_path / "musa-task", task_id="musa-task", scenario="cuda_to_musa")
    view = method_adapter.build_workspace(
        [task_root],
        output_root=tmp_path / "adapter",
        run_id="musa",
        model="model-x",
        api_base="https://example.invalid/v1",
        runtime_images={"cuda_to_musa": "migration/musa:s4000"},
    )
    config = json.loads(
        (Path(view["tasks"]["musa-task"]["task_root"]) / "config.json").read_text()
    )
    assert config["language"] == "python"
    assert config["backend_id"] == "python@1"


def test_build_workspace_accepts_an_attempt_workspace(tmp_path):
    task_root = _task_package(tmp_path / "task-a")
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "main.c").write_text("int f(void) { return 0; }\n", encoding="utf-8")

    view = method_adapter.build_workspace(
        [task_root],
        output_root=tmp_path / "adapter",
        run_id="attempt",
        model="model-x",
        api_base="https://example.invalid/v1",
        runtime_images={"ipp_to_vsipl": "migration/ipp:cpu"},
        workspaces={"task-a": workspace},
    )
    entry = view["tasks"]["task-a"]
    snapshot = tmp_path / "adapter" / "tasks" / "task-a" / "source_snapshot"
    assert entry["repository_root"] == str(snapshot)
    assert entry["task_workspace"] == str(workspace.resolve())
    assert entry["bundle_destination"] == str(workspace.resolve() / "component_bundle")
    assert (snapshot / "src" / "main.c").is_file()
    registry = load_registry(Path(view["registry"]))
    resolved = resolve_run(registry, "attempt", "task-a")
    assert resolved["repository"] == snapshot


def test_method_arm_prompts_are_fixed_and_hashed():
    from migration_scenario_validation.tools import migration_trial

    hashes = migration_trial._prompt_hashes()
    assert set(hashes) == {
        "workflow",
        "extraction_system",
        "focus_context_instructions",
        "protocol_contract_instructions",
        "protocol_contract_schema",
        "retrieval_system",
        "retrieval_instance",
    }
    assert all(len(value) == 64 for value in hashes.values())
    assert migration_trial.ARM_DSH_PROFILES["default"] == "component-method"
    assert migration_trial.ARM_DSH_PROFILES["method"] == "component-method-migration"
    assert migration_trial.METHOD_MAIN_PROFILE == "component-method-migration"


def test_method_tool_line_replaces_the_plain_agent_sentence():
    from migration_scenario_validation.tools import agent_trial, migration_trial

    for prompt in (
        migration_trial.IPP_SYSTEM_PROMPT,
        agent_trial.SYSTEM_PROMPT,
        migration_trial.MUSA_SYSTEM_PROMPT,
    ):
        assert migration_trial.TASK_TOOL_LINE in prompt
        swapped = prompt.replace(
            migration_trial.TASK_TOOL_LINE, migration_trial.METHOD_TOOL_LINE
        )
        assert migration_trial.METHOD_TOOL_LINE in swapped
        assert migration_trial.TASK_TOOL_LINE not in swapped

def test_kylin_prompt_maps_work_prefix_to_workspace():
    from migration_scenario_validation.tools import agent_trial
    from migration_scenario_validation.shared.harness import taskmodel

    task_root = (
        Path(__file__).resolve().parents[2]
        / "migration_scenario_validation"
        / "v3"
        / "windows_to_kylin"
        / "tasks"
        / "negative_win32_eventlog"
    )
    task = taskmodel.load_task(task_root)
    task["spec"] = "Update work/foo and report the result.\n"
    prompt = agent_trial._task_prompt(task, task_root)
    assert "work/foo" in prompt
    assert "relative to `/workspace`" in prompt
    assert "do not create a nested `work/` directory" in prompt
