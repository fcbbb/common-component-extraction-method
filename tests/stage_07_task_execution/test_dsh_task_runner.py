"""Verify the DSH final-task boundary without calling a real model."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from component_method.agent_runtime.contracts import AgentRunResult


CORE = (
    Path(__file__).resolve().parents[2]
    / "src/component_method/task_execution/core"
)
ADAPTERS = CORE.parent / "adapters"
sys.path[:0] = [str(CORE), str(ADAPTERS)]

import task_dsh  # noqa: E402


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=repo, text=True
    ).strip()


@pytest.mark.parametrize("legacy_pathlib", [False, True])
def test_patch_checker_captures_real_worktree_and_checks_clean_index(tmp_path, legacy_pathlib):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repo, check=True
    )
    (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "module.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base_commit = _git(repo, "rev-parse", "HEAD")
    (repo / "module.py").write_text("VALUE = 2\n", encoding="utf-8")

    command = list(task_dsh.patch_checker_command(base_commit))
    command[0] = sys.executable
    if legacy_pathlib:
        command[2] = (
            "from pathlib import Path\n"
            "original_unlink = Path.unlink\n"
            "def legacy_unlink(self):\n"
            "    return original_unlink(self)\n"
            "Path.unlink = legacy_unlink\n"
        ) + command[2]
    checked = subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert checked.returncode == 0, checked.stderr
    patch = _git(repo, "diff", "--cached", "--binary", base_commit)
    assert patch.startswith("diff --git ")
    assert "+VALUE = 2" in patch


def test_patch_checker_rejects_empty_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repo, check=True
    )
    (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "module.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)

    command = list(task_dsh.patch_checker_command(_git(repo, "rev-parse", "HEAD")))
    command[0] = sys.executable
    checked = subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert checked.returncode != 0
    assert "no complete Git patch" in checked.stdout


class _FakeContainer:
    id = "container-id"
    name = "task-container"
    status = "created"

    def __init__(self):
        self.removed = False

    def start(self):
        self.status = "running"

    def reload(self):
        return None

    def exec_run(self, command, **kwargs):
        if command[:2] == ["python", "-c"] and "component_usage.json" in command[2]:
            return SimpleNamespace(
                exit_code=0,
                output=b'{"component_usage":["component-a / entrypoint"]}\n',
            )
        return SimpleNamespace(exit_code=0, output=b"")

    def remove(self, force=False):
        self.removed = force
        self.status = "removed"


class _FakeContainers:
    def __init__(self, container):
        self.container = container
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self.container


class _FakeBackend:
    def __init__(self):
        self.request = None

    def runtime_identity(self):
        return {"backend": "dsh", "dsh_version": "fixture"}

    def run(self, request):
        self.request = request
        request.output_dir.mkdir(parents=True, exist_ok=True)
        (request.output_dir / "trajectory.json").write_text(
            json.dumps(
                {
                    "info": {
                        "runtime_identity": {
                            "backend": "dsh",
                            "dsh_version": "fixture",
                            "system_prompt_sha256": "system",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return AgentRunResult(
            status="Submitted",
            session_id="session-fixture",
            final_output='{"transport":"patch"}',
            messages=[
                {
                    "role": "assistant",
                    "content": '{"component_usage": ["component-b / helper"]}',
                }
            ],
            tool_calls=[],
            model_calls=2,
            input_tokens=20,
            output_tokens=8,
            reported_cost_usd=None,
            completion_validated=True,
            error=None,
        )


def test_run_dsh_task_records_patch_proof_stats_and_identity(tmp_path, monkeypatch):
    container = _FakeContainer()
    containers = _FakeContainers(container)
    client = SimpleNamespace(containers=containers)
    backend = _FakeBackend()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    output = tmp_path / "output"
    patch = "diff --git a/module.py b/module.py\n--- a/module.py\n+++ b/module.py\n"
    monkeypatch.setattr(
        task_dsh,
        "model_env",
        lambda: {
            "OPENAI_API_KEY": "fixture",
            "OPENAI_API_BASE": "http://127.0.0.1.invalid/v1",
            "MODEL_NAME": "fixture-model",
        },
    )
    monkeypatch.setattr(
        task_dsh,
        "settings",
        lambda: {"task_timeout_seconds": 90, "step_limit": 7},
    )
    monkeypatch.setattr(task_dsh, "initialize_task", lambda current, official: None)
    monkeypatch.setattr(
        task_dsh,
        "network_probe",
        lambda current: {
            "network_mode": "none",
            "outbound_connections_blocked": {"1.1.1.1": True},
        },
    )
    monkeypatch.setattr(task_dsh, "collect_patch", lambda *args, **kwargs: patch)
    checked = []
    monkeypatch.setattr(task_dsh, "check_patch", lambda image, value: checked.append((image, value)))
    monkeypatch.setattr(
        task_dsh,
        "agent_bundle_prompt",
        lambda config: "Components at /testbed/component_bundle.",
    )
    monkeypatch.setattr(task_dsh, "task_config_directory", lambda: tmp_path)

    result = task_dsh.run_dsh_task(
        task_id="owner__repo-1",
        arm="components",
        image="fixture-image",
        bundle=bundle,
        official={"base_commit": "a" * 40},
        problem_statement="Change VALUE.",
        out=output,
        client=client,
        backend=backend,
    )

    assert result["status"] == "Submitted"
    assert result["patch"] == patch
    assert result["patch_available"] is True
    assert result["completion_validated"] is True
    assert result["model_calls"] == 2
    assert result["input_tokens"] == 20
    assert result["output_tokens"] == 8
    assert result["runtime_identity"]["backend"] == "dsh"
    assert result["run_identity"]["system_prompt_sha256"] == "system"
    assert result["network_proof"]["container_name"] == "task-container"
    assert result["component_usage"] == [
        "component-b / helper",
        "component-a / entrypoint",
    ]
    assert backend.request.submission_mode == "patch"
    assert backend.request.submission_role == "task"
    assert backend.request.step_limit == 7
    assert backend.request.total_timeout_seconds == 90
    assert backend.request.submission_checker_command[-1] == "a" * 40
    assert containers.create_kwargs["network_mode"] == "none"
    assert containers.create_kwargs["volumes"][str(bundle.resolve())]["mode"] == "ro"
    assert checked == [("fixture-image", patch)]
    assert container.removed is True
    assert (output / "submitted.patch").read_text(encoding="utf-8") == patch
    capture = json.loads((output / "patch_capture.json").read_text(encoding="utf-8"))
    assert capture["clean_baseline_apply_check"] == "passed"
