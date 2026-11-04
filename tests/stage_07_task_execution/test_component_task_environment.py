"""Verify ordinary component tools execute in the task Python environment."""

from types import SimpleNamespace

import pytest

pytest.importorskip("minisweagent")
from component_method.task_execution.runtime_support.docker_environment import ComponentAgentDockerEnvironment
from component_method.component_build.workspace import TASK_RUNTIME_ACTIVATION


def test_ordinary_python_tool_is_automatically_activated():
    commands = []
    def execute(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(output=b"task Python\n", exit_code=0)
    environment = object.__new__(ComponentAgentDockerEnvironment)
    environment.runtime_activation = TASK_RUNTIME_ACTIVATION
    environment.container_name = "fixture"
    environment.config = SimpleNamespace(cwd="/testbed", timeout=30)
    environment.client = SimpleNamespace(containers=SimpleNamespace(
        get=lambda name: SimpleNamespace(exec_run=execute)))
    environment._check_finished = lambda output: None
    result = environment.execute({"command": "python -c 'import numpy'"})
    assert result["returncode"] == 0
    command, options = commands[0]
    assert command[:2] == ["/bin/bash", "-lc"]
    assert TASK_RUNTIME_ACTIVATION in command[-1]
    assert "python -c" in command[-1]
    assert options["environment"]["PYTHONPATH"] == "/testbed"
    assert options["user"] == "10001:10001"
