from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from component_method.agent_runtime.contracts import AgentRunRequest
from component_method.agent_runtime.dsh_headless import (
    DshHeadlessBackend,
    PLUGIN_PACKAGES,
    PROFILE_BY_ROLE,
)


REPOSITORY = Path(__file__).resolve().parents[2]


def _request(tmp_path: Path, **changes) -> AgentRunRequest:
    value = AgentRunRequest(
        run_id="profile-fixture",
        role="extraction",
        model="fixture",
        system_prompt="system",
        task_prompt="task",
        output_dir=tmp_path / "run",
        container_name="fixture",
        container_cwd="/testbed",
        command_timeout_seconds=30,
        total_timeout_seconds=30,
        step_limit=None,
        submission_mode="none",
        submission_role=None,
    )
    return replace(value, **changes)


def _backend() -> DshHeadlessBackend:
    # Node is resolved from COMPONENT_DSH_NODE_BIN or PATH so the test runs on
    # any machine instead of assuming one developer's home directory.
    return DshHeadlessBackend(
        api_key="fixture",
        base_url="https://example.invalid/v1",
        dsh_root=REPOSITORY / "dsh",
        host_environment={},
    )


def test_host_operator_profile_is_selected_explicitly(tmp_path):
    backend = _backend()
    request = _request(tmp_path, profile_name="component-method-host-operator")
    command = backend.build_command(request)
    assert command[command.index("--profile") + 1] == "component-method-host-operator"
    assert "component-method-host-operator/cordis.patch.yml" in command[command.index("--patch") + 1]


def test_role_mapping_is_opt_in_to_preserve_existing_runs(tmp_path, monkeypatch):
    backend = _backend()
    monkeypatch.delenv("COMPONENT_DSH_PROFILE", raising=False)
    monkeypatch.delenv("COMPONENT_DSH_PROFILE_BY_ROLE", raising=False)
    request = _request(tmp_path, role="extraction")
    assert backend.build_command(request)[2] == "component-method"
    monkeypatch.setenv("COMPONENT_DSH_PROFILE_BY_ROLE", "1")
    assert backend.build_command(request)[2] == PROFILE_BY_ROLE["extraction"]


def test_all_declared_plugin_bundles_and_profiles_exist():
    backend = _backend()
    backend.validate_runtime()
    for name, package in PLUGIN_PACKAGES.items():
        path = backend.dsh_root / "plugins" / name / "dist" / "index.js"
        assert path.is_file(), (name, package, path)
    for profile in PROFILE_BY_ROLE.values():
        assert (backend.dsh_root / "profiles" / profile / "cordis.patch.yml").is_file()
