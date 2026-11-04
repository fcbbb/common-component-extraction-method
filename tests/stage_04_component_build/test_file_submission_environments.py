"""Invalid file submissions stay in the agent loop and can be corrected."""

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("minisweagent")
from minisweagent.agents.default import Submitted

from component_method.component_build import submission
from component_method.task_execution.runtime_support.docker_environment import ComponentAgentDockerEnvironment
from component_method.task_execution.runtime_support import restricted_environment


def test_component_completion_checks_files_and_accepts_marker_only_after_correction(tmp_path):
    (tmp_path / "manifest.json").write_text('{"status":"ready","components":['
        '{"status":"draft_ready","library":{"path":"common.py"},'
        '"entrypoints":[{"name":"make","kind":"function"}]}]}')
    (tmp_path / "common.py").write_text("def make(:\n")
    environment = object.__new__(ComponentAgentDockerEnvironment)
    environment.output_role = "extraction"
    environment.runtime_activation = ""
    environment.container_name = "fixture"

    def execute(*args, **kwargs):
        checked = subprocess.run([sys.executable, submission.__file__, "--role", "extraction",
                                  "--output", str(tmp_path)], capture_output=True)
        return SimpleNamespace(exit_code=checked.returncode, output=checked.stdout)

    environment.client = SimpleNamespace(containers=SimpleNamespace(
        get=lambda name: SimpleNamespace(exec_run=execute)))
    invalid = {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", "returncode": 0}
    environment._check_finished(invalid)
    assert invalid["returncode"] == 1
    assert "Submission check failed" in invalid["output"]
    (tmp_path / "common.py").write_text("def make(): return 1\n")
    with pytest.raises(Submitted):
        environment._check_finished({"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", "returncode": 0})


def test_task_completion_returns_checker_errors_for_correction(monkeypatch):
    environment = object.__new__(restricted_environment.RestrictedLocalEnvironment)
    environment.config = SimpleNamespace(env={})
    checks = iter([subprocess.CompletedProcess([], 1, stdout="new.py has a syntax error"),
                   subprocess.CompletedProcess([], 0, stdout="valid")])
    monkeypatch.setattr(restricted_environment, "_run_as_task_user", lambda *args: next(checks))
    invalid = {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nDone", "returncode": 0}
    environment._check_finished(invalid)
    assert invalid["returncode"] == 1
    assert "syntax error" in invalid["output"]
    with pytest.raises(Submitted):
        environment._check_finished({"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nDone", "returncode": 0})


def test_ordinary_commands_do_not_trigger_submission_checks(monkeypatch):
    environment = object.__new__(restricted_environment.RestrictedLocalEnvironment)
    monkeypatch.setattr(restricted_environment, "_run_as_task_user", lambda *args: pytest.fail("unexpected submission check"))
    environment._check_finished({"output": "ordinary output", "returncode": 0})
