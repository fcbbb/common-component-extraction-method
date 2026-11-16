from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from component_method import dsh_jobs, dsh_kernel
from component_method.dsh_registry import RegistryError, load_registry, resolve_run


def _registry(tmp_path: Path) -> tuple[Path, dict]:
    run_root = tmp_path / "run"
    task_root = run_root / "tasks" / "task-a"
    task_root.mkdir(parents=True)
    repository = tmp_path / "repository"
    repository.mkdir()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "schema": "component-method-dsh-registry-v1",
        "runs": {
            "run-a": {
                "run_root": str(run_root),
                "task_id": "task-a",
                "tasks": {
                    "task-a": {
                        "task_root": str(task_root),
                        "repository": str(repository),
                    }
                },
            }
        },
    }), encoding="utf-8")
    return path, load_registry(path)


def test_registry_resolves_registered_task_and_rejects_traversal(tmp_path):
    _, registry = _registry(tmp_path)
    resolved = resolve_run(registry, "run-a", "task-a")
    assert resolved["task_root"].name == "task-a"
    assert resolved["repository"].name == "repository"
    with pytest.raises(RegistryError):
        resolve_run(registry, "../run-a", "task-a")
    with pytest.raises(RegistryError):
        resolve_run(registry, "run-a", "task-b")


def test_stage_command_is_built_without_a_shell(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "extract",
        {"run_id": "run-a", "task_id": "task-a", "workers": 2, "resume": True},
        registry=registry,
    )
    assert result["ok"] is True
    command = captured["command"]
    assert command[:4] == [
        dsh_kernel._python(),
        "-m",
        "component_method.workflow.run_stage",
        "--task-root",
    ]
    assert "--stage" in command and "extract" in command
    assert "--workers" in command and "2" in command
    assert "--resume" in command
    assert captured["kwargs"]["shell"] is False


def test_run_stage_alias_builds_the_registered_stage(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "run_stage",
        {"run_id": "run-a", "task_id": "task-a", "stage": "review", "workers": 1},
        registry=registry,
    )
    assert result["ok"] is True
    command = captured["command"]
    assert command[command.index("--stage") + 1] == "review"
    assert command[command.index("--workers") + 1] == "1"


def test_stage_rejects_output_paths_outside_run_root(tmp_path):
    _, registry = _registry(tmp_path)
    result = dsh_kernel.execute_method(
        "signal_prepare",
        {"run_id": "run-a", "output_dir": str(tmp_path / "outside")},
        registry=registry,
    )
    assert result["ok"] is False
    assert "inside the registered run root" in result["error"]


def test_unknown_method_is_rejected():
    with pytest.raises(dsh_kernel.KernelError):
        dsh_kernel.execute_method("arbitrary_python", {})


def test_job_manager_records_success(tmp_path):
    job_root = tmp_path / "jobs"
    status = dsh_jobs.start_job(
        job_root=job_root,
        method="fixture",
        command=[sys.executable, "-c", "print('job-ok')"],
        cwd=tmp_path,
        environment={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    job_id = status["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = dsh_jobs.job_status(job_root, job_id)
        if current["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    current = dsh_jobs.job_status(job_root, job_id)
    assert current["status"] == "succeeded"
    assert current["exit_code"] == 0
    assert "job-ok" in current["stdout_tail"]


def test_job_manager_rejects_unknown_job(tmp_path):
    current = dsh_jobs.job_status(tmp_path / "jobs", "not-a-job")
    assert current["status"] == "missing"


def test_check_submission_uses_controller_environment(tmp_path, monkeypatch):
    output = tmp_path / "submission"
    output.mkdir()
    (output / "manifest.json").write_text('{"components": []}\n', encoding="utf-8")
    monkeypatch.setenv("COMPONENT_DSH_OUTPUT_HOST_DIR", str(output))
    monkeypatch.setenv("COMPONENT_DSH_SUBMISSION_ROLE", "extraction")
    result = dsh_kernel.execute_method("check_submission", {})
    assert result == {"ok": True, "role": "extraction"}
