import json
from types import SimpleNamespace

import pytest

from component_method.component_build.extraction.runner import ComponentAgentRunner, _task_visible_volumes
from component_method.task_execution.runtime_support.build_helpers import _verify_isolated_container


@pytest.fixture
def agent_container(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    components = tmp_path / "components"
    components.mkdir()
    submission = tmp_path / "submission"
    submission.mkdir()
    volumes = _task_visible_volumes(workspace, tmp_path / "output", components, submission)
    return SimpleNamespace(
        reload=lambda: None,
        attrs={
            "Mounts": [
                {"Type": "bind", "Destination": volume["bind"], "RW": volume["mode"] == "rw"}
                for volume in volumes.values()
            ] + [{"Type": "tmpfs", "Destination": "/tmp"}],
            "HostConfig": {"NetworkMode": "none"},
        },
    )


def test_actual_agent_mounts_pass_isolation(agent_container):
    _verify_isolated_container(agent_container)


def test_language_support_mount_must_be_read_only(agent_container):
    helper = next(mount for mount in agent_container.attrs["Mounts"]
                  if mount["Destination"] == "/component-tools/language_support.py")
    helper["RW"] = True
    with pytest.raises(RuntimeError, match="Only the designated component output"):
        _verify_isolated_container(agent_container)


def test_testbed_image_volume_tmpfs_is_allowed(agent_container):
    agent_container.attrs["Mounts"].append(
        {"Type": "tmpfs", "Destination": "/testbed/mnt_tmp"}
    )
    _verify_isolated_container(agent_container)


def test_unknown_tmpfs_mount_is_rejected(agent_container):
    agent_container.attrs["Mounts"].append(
        {"Type": "tmpfs", "Destination": "/unexpected"}
    )
    with pytest.raises(RuntimeError, match="Unexpected non-repository"):
        _verify_isolated_container(agent_container)


def test_unknown_bind_mount_is_rejected(agent_container):
    agent_container.attrs["Mounts"].append(
        {"Type": "bind", "Destination": "/unexpected", "RW": False}
    )
    with pytest.raises(RuntimeError, match="Repository containers may bind only"):
        _verify_isolated_container(agent_container)


def test_agent_network_must_be_disabled(agent_container):
    agent_container.attrs["HostConfig"]["NetworkMode"] = "bridge"
    with pytest.raises(RuntimeError, match="unexpected network mode"):
        _verify_isolated_container(agent_container)


def test_failure_manifest_preserves_agent_status_and_dsh_session(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "agent_status.json").write_text('{"exit_status": "AgentProcessError"}\n')
    (output / "dsh_session.json").write_text('{"session_id": "session-1"}\n')
    runner = ComponentAgentRunner.__new__(ComponentAgentRunner)
    runner._write_failure_manifest(
        output, tmp_path / "submission", "AgentProcessError", "root cause"
    )
    failure = json.loads((output / "failure.json").read_text())
    assert failure["status"] == "AgentProcessError"
    assert failure["error"] == "root cause"
    assert failure["dsh_session"] == {"session_id": "session-1"}
    assert (output / "agent_status.json").is_file()
