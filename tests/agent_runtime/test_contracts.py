from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from component_method.agent_runtime import (
    AgentRunRequest,
    AgentRunResult,
    BackendSettings,
    create_agent_backend,
    register_agent_backend,
)
from component_method.agent_runtime.backend import selected_backend_name
from component_method.agent_runtime import factory


def test_agent_request_and_result_are_immutable(tmp_path):
    request = AgentRunRequest(
        run_id="fixture",
        role="extraction",
        model="model",
        system_prompt="system",
        task_prompt="task",
        output_dir=tmp_path,
        container_name="container",
        container_cwd="/testbed",
        command_timeout_seconds=120,
        total_timeout_seconds=600,
        step_limit=25,
        submission_mode="files",
        submission_role="extraction",
        submission_checker_command=("python", "/checker.py", "--submit"),
    )
    result = AgentRunResult(
        status="Submitted",
        session_id="session",
        final_output="done",
        messages=[],
        tool_calls=[],
        model_calls=1,
        input_tokens=None,
        output_tokens=None,
        reported_cost_usd=None,
        completion_validated=True,
        error=None,
    )
    assert request.output_dir == Path(tmp_path)
    assert request.submission_checker_command[-1] == "--submit"
    assert result.completion_validated is True
    with pytest.raises(FrozenInstanceError):
        request.role = "review"


def test_backend_selection_defaults_to_dsh_and_rejects_other_values():
    assert selected_backend_name({}) == "dsh"
    assert selected_backend_name({"AGENT_BACKEND": " DSH "}) == "dsh"
    with pytest.raises(ValueError, match="AGENT_BACKEND"):
        selected_backend_name({"AGENT_BACKEND": "unknown"})


def test_registered_backend_is_selectable_without_workflow_changes(monkeypatch):
    class FixtureBackend:
        def run(self, request):
            raise AssertionError("not exercised")

        def runtime_identity(self):
            return {"backend": "fixture"}

    monkeypatch.setattr(factory, "_BACKEND_BUILDERS", dict(factory._BACKEND_BUILDERS))
    register_agent_backend("fixture", lambda settings: FixtureBackend())

    assert selected_backend_name({"AGENT_BACKEND": "fixture"}) == "fixture"
    backend = create_agent_backend(
        BackendSettings(api_key="key", base_url="https://example.invalid/v1"),
        environment={"AGENT_BACKEND": "fixture"},
    )
    assert backend.runtime_identity() == {"backend": "fixture"}
