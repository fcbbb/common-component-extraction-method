from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from component_method import dsh_jobs, dsh_kernel, dsh_registry
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


def test_registry_cli_writes_a_round_trippable_document(tmp_path):
    path = tmp_path / "registry.json"
    run_root = tmp_path / "run"
    run_root.mkdir()
    task_root = run_root / "task-a"
    task_root.mkdir()
    dsh_registry.main(["init", "--registry", str(path)])
    dsh_registry.main([
        "add-run", "--registry", str(path), "--run-id", "run-a",
        "--run-root", str(run_root), "--embedding-dir", "custom_embeddings",
    ])
    dsh_registry.main([
        "add-task", "--registry", str(path), "--run-id", "run-a",
        "--task-id", "task-a", "--task-root", str(task_root),
    ])
    registry = load_registry(path)
    resolved = resolve_run(registry, "run-a", "task-a")
    assert resolved["task_root"] == task_root.resolve()
    assert registry["runs"]["run-a"]["embedding_dir"] == "custom_embeddings"
    with pytest.raises(RegistryError):
        dsh_registry.main(["init", "--registry", str(path)])


def test_run_embedding_dir_comes_from_registry_metadata(tmp_path, monkeypatch):
    run_root = tmp_path / "run"
    custom = run_root / "custom_embeddings"
    custom.mkdir(parents=True)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "schema": "component-method-dsh-registry-v1",
        "runs": {
            "run-a": {
                "run_root": str(run_root),
                "embedding_dir": "custom_embeddings",
                "tasks": {},
            }
        },
    }), encoding="utf-8")
    registry = load_registry(path)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "signal_prepare", {"run_id": "run-a"}, registry=registry
    )
    assert result["ok"] is True
    command = captured["command"]
    assert command[command.index("--output-dir") + 1] == str(custom)


def test_ops_arguments_are_allow_listed_per_module(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "ops",
        {"module": "preflight", "args": ["--task", "task-a"]},
        registry=registry,
    )
    assert result["ok"] is True
    assert captured["command"][-2:] == ["--task", "task-a"]
    for rejected in (["--output", "/tmp/x"], ["/bin/sh"]):
        result = dsh_kernel.execute_method(
            "ops", {"module": "preflight", "args": rejected}, registry=registry
        )
        assert result["ok"] is False
        assert "ops module preflight" in result["error"]


def test_kernel_reads_repository_from_environment(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setenv("COMPONENT_DSH_REPOSITORY", str(repository))
    assert dsh_kernel._repository_from_environment() == repository.resolve()
    monkeypatch.setenv("COMPONENT_DSH_REPOSITORY", str(tmp_path / "missing"))
    with pytest.raises(dsh_kernel.KernelError):
        dsh_kernel._repository_from_environment()
    monkeypatch.delenv("COMPONENT_DSH_REPOSITORY")
    assert dsh_kernel._repository_from_environment() is None


def _write_task_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stage_command_is_built_without_a_shell(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "inputs" / "focus_context_packets.json", {"packet_count": 1})
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
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "inputs" / "frozen_components.json", {"components": []})
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
    assert command[command.index("--stage") + 1] == "audit"
    assert command[command.index("--steps") + 1] == "review"
    assert command[command.index("--workers") + 1] == "1"


def test_stage_prerequisite_is_enforced_before_spawning(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "extract",
        {"run_id": "run-a", "task_id": "task-a"},
        registry=registry,
    )
    assert result["ok"] is False
    assert result["error_code"] == "STAGE_INPUT_MISSING"
    assert called == []


def test_run_stage_alias_checks_the_requested_stage_prerequisite(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "inputs" / "frozen_components.json", {"components": []})
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "run_stage",
        {"run_id": "run-a", "task_id": "task-a", "stage": "curate"},
        registry=registry,
    )
    assert result["ok"] is False
    assert result["error_code"] == "STAGE_INPUT_MISSING"
    assert called == []


def test_migration_workspace_runs_prepare_reviews_and_review(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "config.json", {
        "task_id": "task-a",
        "source_scan_mode": "migration",
    })
    _write_task_json(
        task_root / "runs" / "task-a" / "extraction_v1" / "curated" / "summary.json",
        {"status": "completed"},
    )
    _write_task_json(task_root / "inputs" / "focus_context_packets.json", {"packet_count": 1})
    _write_task_json(task_root / "inputs" / "frozen_components.json", {"component_count": 1})
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    for method, payload in (
        ("run_stage", {"run_id": "run-a", "task_id": "task-a", "stage": "prepare_reviews"}),
        ("review", {"run_id": "run-a", "task_id": "task-a"}),
    ):
        result = dsh_kernel.execute_method(method, payload, registry=registry)
        assert result["ok"] is True, result
    assert [command[command.index("--stage") + 1] for command in called] == [
        "build",
        "audit",
    ]


def test_migration_workspace_rejects_task_and_report_stages(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "config.json", {
        "task_id": "task-a",
        "source_scan_mode": "migration",
    })
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    for method, payload in (
        ("task", {"run_id": "run-a", "task_id": "task-a"}),
        ("run_stage", {"run_id": "run-a", "task_id": "task-a", "stage": "report"}),
    ):
        result = dsh_kernel.execute_method(method, payload, registry=registry)
        assert result["ok"] is False
        assert result["error_code"] == "STAGE_UNSUPPORTED"
    assert called == []


def test_migration_workspace_allows_retrieval_but_rejects_task(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "config.json", {
        "task_id": "task-a",
        "source_scan_mode": "migration",
    })
    _write_task_json(
        task_root / "outputs" / "full_library" / "manifest.json",
        {"component_count": 1},
    )
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "run_stage",
        {"run_id": "run-a", "task_id": "task-a", "stage": "retrieval"},
        registry=registry,
    )
    assert result["ok"] is True, result
    assert called[0][called[0].index("--stage") + 1] == "retrieval"

    called.clear()
    for stage in ("task", "deliver"):
        result = dsh_kernel.execute_method(
            "run_stage",
            {"run_id": "run-a", "task_id": "task-a", "stage": stage},
            registry=registry,
        )
        assert result["ok"] is False
        assert result["error_code"] == "STAGE_UNSUPPORTED"
    assert called == []


def test_deliver_group_builds_both_blocks(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(
        task_root / "outputs" / "full_library" / "manifest.json",
        {"component_count": 1},
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "run_stage",
        {"run_id": "run-a", "task_id": "task-a", "stage": "deliver"},
        registry=registry,
    )
    assert result["ok"] is True, result
    command = captured["command"]
    assert command[command.index("--blocks") + 1] == "retrieval,task"


def test_stage_lock_reports_busy_without_running(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "inputs" / "focus_context_packets.json", {"packet_count": 1})
    held = dsh_kernel._try_stage_lock(task_root)
    assert held is not None
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    try:
        result = dsh_kernel.execute_method(
            "extract",
            {"run_id": "run-a", "task_id": "task-a"},
            registry=registry,
        )
    finally:
        dsh_kernel._release_stage_lock(held)
    assert result["ok"] is False
    assert result["error_code"] == "STAGE_BUSY"
    assert called == []


def test_stage_result_reports_manifest_summary_and_artifacts(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "inputs" / "focus_context_packets.json", {"packet_count": 3})
    _write_task_json(task_root / "config.json", {"task_id": "task-a"})
    summary = task_root / "runs" / "task-a" / "extraction_v1" / "summary.json"
    _write_task_json(summary, {
        "status": "succeeded",
        "component_count": 4,
        "packet_count": 3,
    })

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "extract",
        {"run_id": "run-a", "task_id": "task-a"},
        registry=registry,
    )
    assert result["ok"] is True
    assert result["summary"]["component_count"] == 4
    assert result["artifacts"]["manifest"] == str(summary)


def test_publish_library_prerequisite_follows_publish_mode(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "config.json", {
        "task_id": "task-a",
        "publish_mode": "migration_direct",
    })
    curated = task_root / "runs" / "task-a" / "extraction_v1" / "curated" / "summary.json"
    _write_task_json(curated, {"status": "completed"})
    called = []

    def fake_run(command, **kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dsh_kernel.subprocess, "run", fake_run)
    result = dsh_kernel.execute_method(
        "publish_library",
        {"run_id": "run-a"},
        registry=registry,
    )
    assert result["ok"] is True
    assert called and called[0][called[0].index("--stage") + 1] == "publish"


def test_publish_library_requires_review_summary_without_direct_mode(tmp_path):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "config.json", {"task_id": "task-a"})
    result = dsh_kernel.execute_method(
        "publish_library",
        {"run_id": "run-a"},
        registry=registry,
    )
    assert result["ok"] is False
    assert result["error_code"] == "STAGE_INPUT_MISSING"


def test_job_stage_command_holds_the_stage_lock(tmp_path):
    _, registry = _registry(tmp_path)
    task_root = tmp_path / "run" / "tasks" / "task-a"
    _write_task_json(task_root / "inputs" / "focus_context_packets.json", {"packet_count": 1})
    command = dsh_kernel._command_for_job(
        "extract",
        {"run_id": "run-a", "task_id": "task-a"},
        registry,
    )
    assert command[:6] == [
        dsh_kernel._python(),
        "-m",
        "component_method.workflow.stage_lock",
        "--lock-root",
        str(task_root),
        "--",
    ]
    assert command[6:8] == [dsh_kernel._python(), "-m"]
    assert "component_method.workflow.run_stage" in command


def test_stage_lock_wrapper_waits_for_the_lock(tmp_path):
    lock_root = tmp_path / "task"
    held = dsh_kernel._try_stage_lock(lock_root)
    assert held is not None
    module = dsh_kernel.PROJECT / "src" / "component_method" / "workflow" / "stage_lock.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(module),
            "--lock-root",
            str(lock_root),
            "--",
            sys.executable,
            "-c",
            "print('ran')",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.2)
        assert process.poll() is None
    finally:
        dsh_kernel._release_stage_lock(held)
    output, _ = process.communicate(timeout=10)
    assert process.returncode == 0
    assert "ran" in output


def test_stage_lock_wrapper_forwards_cancellation_to_the_stage(tmp_path):
    lock_root = tmp_path / "task"
    marker = tmp_path / "child-saw-term"
    module = dsh_kernel.PROJECT / "src" / "component_method" / "workflow" / "stage_lock.py"
    child = (
        "import signal, sys, time\n"
        "def stop(*args):\n"
        "    open(sys.argv[1], 'w').write('terminated')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(module),
            "--lock-root",
            str(lock_root),
            "--",
            sys.executable,
            "-c",
            child,
            str(marker),
        ],
    )
    try:
        time.sleep(0.5)
        assert process.poll() is None
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert process.returncode == 0
    assert marker.read_text(encoding="utf-8") == "terminated"


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


def test_job_status_returns_stage_summary_and_failure_code(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPONENT_DSH_JOB_ROOT", str(tmp_path / "jobs"))
    task_root = tmp_path / "task"
    extraction = task_root / "runs" / "task-a" / "extraction_v1"
    extraction.mkdir(parents=True)
    (task_root / "config.json").write_text(
        json.dumps({"task_id": "task-a"}), encoding="utf-8"
    )
    (extraction / "summary.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "packet_count": 2,
                "successful_packets": 2,
                "failed_packets": 0,
                "component_count": 3,
                "extraction_api_calls": 4,
            }
        ),
        encoding="utf-8",
    )
    status = dsh_jobs.start_job(
        job_root=tmp_path / "jobs",
        method="extract",
        command=[sys.executable, "-c", "import time; time.sleep(0.1)"],
        cwd=tmp_path,
        environment={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tmp_path)},
        context={
            "run_id": "run-a",
            "task_id": "task-a",
            "run_root": str(tmp_path / "run"),
            "task_root": str(task_root),
        },
    )
    job_id = status["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if dsh_jobs.job_status(tmp_path / "jobs", job_id)["status"] == "succeeded":
            break
        time.sleep(0.05)
    result = dsh_kernel._status_job({"job_id": job_id}, {})
    assert result["ok"] is True
    assert result["summary"]["successful_packets"] == 2
    assert result["artifacts"]["manifest"].endswith("summary.json")

    failed = dsh_jobs.start_job(
        job_root=tmp_path / "jobs",
        method="extract",
        command=[sys.executable, "-c", "raise SystemExit(2)"],
        cwd=tmp_path,
        environment={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tmp_path)},
        context={"task_root": str(task_root), "task_id": "task-a"},
    )
    failed_id = failed["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if dsh_jobs.job_status(tmp_path / "jobs", failed_id)["status"] == "failed":
            break
        time.sleep(0.05)
    failed_result = dsh_kernel._status_job({"job_id": failed_id}, {})
    assert failed_result["ok"] is False
    assert failed_result["error_code"] == "STAGE_FAILED"


def test_check_submission_uses_controller_environment(tmp_path, monkeypatch):
    output = tmp_path / "submission"
    output.mkdir()
    (output / "manifest.json").write_text('{"components": []}\n', encoding="utf-8")
    monkeypatch.setenv("COMPONENT_DSH_OUTPUT_HOST_DIR", str(output))
    monkeypatch.setenv("COMPONENT_DSH_SUBMISSION_ROLE", "extraction")
    result = dsh_kernel.execute_method("check_submission", {})
    assert result == {"ok": True, "role": "extraction"}


def test_offline_task_root_honours_environment(tmp_path, monkeypatch):
    from component_method import runtime_paths

    task = tmp_path / "offline" / "task-a"
    task.mkdir(parents=True)
    monkeypatch.setenv("COMPONENT_DSH_OFFLINE_TASKS", str(tmp_path / "offline"))
    assert runtime_paths.offline_task_root("task-a") == task.resolve()


def test_job_status_is_recorded_after_the_starting_process_exits(tmp_path):
    """The DSH kernel exits right after printing a job id.

    The job therefore has to record its own terminal status; a monitor thread
    in the starting process would die with it and leave ``running`` forever.
    """
    job_root = tmp_path / "jobs"
    repository = Path(__file__).resolve().parents[2]
    starter = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from component_method.dsh_jobs import start_job\n"
        "status = start_job(\n"
        "    job_root=Path(sys.argv[1]), method='fixture',\n"
        "    command=[sys.executable, '-c', \"import time; time.sleep(0.2); print('job-ok')\"],\n"
        "    cwd=Path(sys.argv[2]),\n"
        "    environment={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': sys.argv[2],\n"
        "                 'PYTHONPATH': sys.argv[3]},\n"
        ")\n"
        "print(status['job_id'])\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", starter, str(job_root), str(tmp_path), str(repository / "src")],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYTHONPATH": str(repository / "src"),
        },
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    job_id = completed.stdout.strip().splitlines()[-1]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = dsh_jobs.job_status(job_root, job_id)
        if current["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    current = dsh_jobs.job_status(job_root, job_id)
    assert current["status"] == "succeeded", current
    assert current["exit_code"] == 0
    assert "job-ok" in current["stdout_tail"]


def test_run_stage_routes_in_process_stages_through_one_entry(tmp_path, monkeypatch):
    _, registry = _registry(tmp_path)
    for name in (
        "COMPONENT_DSH_COMPONENT_LIBRARY",
        "COMPONENT_DSH_SELECTION_PATH",
        "COMPONENT_DSH_COVERAGE_PATH",
        "COMPONENT_DSH_TASK_ID",
        "COMPONENT_DSH_BUNDLE_DESTINATION",
    ):
        monkeypatch.delenv(name, raising=False)
    result = dsh_kernel.execute_method(
        "run_stage",
        {"run_id": "run-a", "task_id": "task-a", "stage": "validate_selection"},
        registry=registry,
    )
    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["method"] == "run_stage"
    assert result["stage"] == "validate_selection"
    assert result["error_code"] == "STAGE_INPUT_MISSING"
    assert result["summary"] == {}
    json.dumps(result)


def test_run_stage_returns_the_same_sheet_for_an_in_process_stage(monkeypatch):
    monkeypatch.setitem(
        dsh_kernel.METHODS,
        "catalog",
        lambda payload, registry: dsh_kernel._envelope(
            method="catalog", status="succeeded", summary={"component_count": 3}
        ),
    )
    result = dsh_kernel.execute_method(
        "run_stage", {"run_id": "run-a", "stage": "catalog"}, registry={}
    )
    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["method"] == "run_stage"
    assert result["stage"] == "catalog"
    assert result["summary"] == {"component_count": 3}
    assert result["error_code"] is None
    json.dumps(result)


def test_materialize_selection_is_json_safe(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    selection = tmp_path / "selection.json"
    selection.write_text("{}", encoding="utf-8")
    destination = tmp_path / "bundle"
    destination.mkdir()
    (destination / "manifest.json").write_text(
        json.dumps({"component_count": 2}), encoding="utf-8"
    )
    monkeypatch.setenv("COMPONENT_DSH_COMPONENT_LIBRARY", str(library))
    monkeypatch.setenv("COMPONENT_DSH_SELECTION_PATH", str(selection))
    monkeypatch.setenv("COMPONENT_DSH_BUNDLE_DESTINATION", str(destination))
    from component_method.retrieval import selection_bundle

    monkeypatch.setattr(
        selection_bundle, "materialize_selected_bundle", lambda *args, **kwargs: destination
    )
    result = dsh_kernel._materialize_selection({}, {})
    assert result["status"] == "succeeded"
    assert result["summary"]["bundle"] == str(destination)
    assert result["summary"]["component_count"] == 2
    assert result["artifacts"]["bundle"] == str(destination)
    json.dumps(result)
