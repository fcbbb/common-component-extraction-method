from dataclasses import replace
import json
from pathlib import Path
import time

from component_method.agent_runtime.contracts import AgentRunRequest
from component_method.agent_runtime.dsh_headless import DshHeadlessBackend
from component_method.component_build.extraction.runner import ComponentAgentRunner


def _make_runtime(tmp_path: Path):
    dsh_root = tmp_path / "dsh"
    (dsh_root / "profiles/component-method").mkdir(parents=True)
    (dsh_root / "plugins/controlled-bash/dist").mkdir(parents=True)
    (dsh_root / "package.json").write_text(
        json.dumps({"dependencies": {"@deepseek-ai/dsh": "0.2.2-rc.1"}}),
        encoding="utf-8",
    )
    (dsh_root / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (dsh_root / "profiles/component-method/cordis.patch.yml").write_text("[]\n")
    (dsh_root / "plugins/controlled-bash/dist/index.js").write_text(
        "export default function () {}\n"
    )
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\necho v24.9.0\n")
    node.chmod(0o755)
    dsh = dsh_root / "fake-dsh"
    dsh.write_text(
        """#!/usr/bin/python3
import json, os, pathlib, sys
task = sys.stdin.read()
target = pathlib.Path(os.environ['COMPONENT_DSH_VALIDATED_SUBMISSION_PATH'])
target.write_text(json.dumps({
    'validated': True,
    'transport': 'files',
    'role': os.environ['COMPONENT_DSH_SUBMISSION_ROLE'],
    'container_name': os.environ['COMPONENT_DSH_CONTAINER_NAME'],
    'checker_exit_code': 0,
}))
target.with_name('child_environment.json').write_text(json.dumps({
    'host_secret': os.environ.get('HOST_SECRET'),
    'task': task,
    'dsh_home': os.environ.get('DSH_HOME'),
    'checker_command': os.environ.get('COMPONENT_DSH_CHECKER_COMMAND_JSON'),
}))
session = sys.argv[sys.argv.index('--session-id') + 1] if '--session-id' in sys.argv else 'session-new'
for event in [
    {'type': 'session', 'sessionId': session},
    {'type': 'tool_call', 'callId': 'call-1', 'tool': 'controlled_bash',
     'input': {'command': 'pwd', 'cwd': '/testbed', 'timeout_seconds': 5}},
    {'type': 'tool_result', 'callId': 'call-1', 'status': 'completed', 'result': 'ok'},
    {'type': 'status', 'phase': 'step_end', 'step': 1,
     'usage': {'inputTokens': 5, 'outputTokens': 2}},
    {'type': 'final', 'sessionId': session, 'reason': {'kind': 'completed'}, 'text': 'done'},
]:
    print(json.dumps(event), flush=True)
""",
        encoding="utf-8",
    )
    dsh.chmod(0o755)
    return dsh_root, node, dsh


def _request(tmp_path: Path, *, resume_session_id=None):
    return AgentRunRequest(
        run_id="fixture",
        role="extraction",
        model="fixture-model",
        system_prompt="system prompt",
        task_prompt="task prompt",
        output_dir=tmp_path / "run",
        container_name="fixture-container",
        container_cwd="/testbed",
        command_timeout_seconds=30,
        total_timeout_seconds=30,
        step_limit=None,
        submission_mode="files",
        submission_role="extraction",
        resume_session_id=resume_session_id,
        submission_checker_command=("python", "/checker.py", "--submit"),
    )


def test_dsh_backend_runs_json_cli_with_minimal_environment(tmp_path):
    dsh_root, node, dsh = _make_runtime(tmp_path)
    request = _request(tmp_path)
    profile = request.output_dir / "dsh_home/profiles/component-method/package.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n")
    backend = DshHeadlessBackend(
        api_key="secret-api-key",
        base_url="https://example.invalid/v1",
        dsh_root=dsh_root,
        dsh_bin=dsh,
        node_bin=node,
        host_environment={"HOST_SECRET": "must-not-leak"},
    )

    result = backend.run(request)
    child_environment = json.loads(
        (request.output_dir / "child_environment.json").read_text()
    )
    trajectory = json.loads((request.output_dir / "trajectory.json").read_text())

    assert result.status == "Submitted"
    assert result.session_id == "session-new"
    assert result.completion_validated is True
    assert child_environment["host_secret"] is None
    assert child_environment["task"] == "task prompt"
    assert child_environment["dsh_home"].endswith("/run/dsh_home")
    assert json.loads(child_environment["checker_command"]) == [
        "python",
        "/checker.py",
        "--submit",
    ]
    assert trajectory["info"]["runtime_identity"]["dsh_version"] == "0.2.2-rc.1"
    assert trajectory["info"]["runtime_identity"]["node_version"] == "24.9.0"


def test_dsh_backend_enforces_step_limit_while_process_is_running(tmp_path):
    dsh_root, node, dsh = _make_runtime(tmp_path)
    dsh.write_text(
        """#!/usr/bin/python3
import json, sys, time
sys.stdin.read()
print(json.dumps({'type': 'session', 'sessionId': 'session-step-limit'}), flush=True)
print(json.dumps({
    'type': 'status', 'phase': 'step_end', 'step': 1,
    'usage': {'inputTokens': 5, 'outputTokens': 2},
}), flush=True)
time.sleep(30)
""",
        encoding="utf-8",
    )
    dsh.chmod(0o755)
    request = replace(
        _request(tmp_path),
        step_limit=1,
        total_timeout_seconds=20,
        submission_checker_command=None,
    )
    profile = request.output_dir / "dsh_home/profiles/component-method/package.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n")
    backend = DshHeadlessBackend(
        api_key="secret",
        base_url="https://example.invalid/v1",
        dsh_root=dsh_root,
        dsh_bin=dsh,
        node_bin=node,
        host_environment={},
    )

    started = time.monotonic()
    result = backend.run(request)

    assert time.monotonic() - started < 5
    assert result.status == "LimitsExceeded"
    assert result.model_calls == 1
    assert result.completion_validated is False
    assert "step limit of 1" in result.error


def test_dsh_resume_command_uses_exact_session_id(tmp_path):
    dsh_root, node, dsh = _make_runtime(tmp_path)
    request = _request(tmp_path, resume_session_id="session-existing")
    backend = DshHeadlessBackend(
        api_key="secret",
        base_url="https://example.invalid/v1",
        dsh_root=dsh_root,
        dsh_bin=dsh,
        node_bin=node,
        host_environment={},
    )

    assert backend.build_command(request)[-3:] == [
        "--session-id",
        "session-existing",
        "-",
    ]


def test_dsh_resume_parses_only_the_current_appended_event_segment(tmp_path):
    dsh_root, node, dsh = _make_runtime(tmp_path)
    first = _request(tmp_path)
    profile = first.output_dir / "dsh_home/profiles/component-method/package.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n")
    backend = DshHeadlessBackend(
        api_key="secret",
        base_url="https://example.invalid/v1",
        dsh_root=dsh_root,
        dsh_bin=dsh,
        node_bin=node,
        host_environment={},
    )
    assert backend.run(first).session_id == "session-new"

    resumed = _request(tmp_path, resume_session_id="session-new")
    result = backend.run(resumed)
    raw_events = (resumed.output_dir / "dsh_events.jsonl").read_text()

    assert result.status == "Submitted"
    assert result.session_id == "session-new"
    assert raw_events.count('"type": "final"') == 2
    assert not (resumed.output_dir / ".dsh_events.current.jsonl").exists()


def test_runtime_identity_changes_with_plugin_bundle(tmp_path):
    dsh_root, node, dsh = _make_runtime(tmp_path)
    backend = DshHeadlessBackend(
        api_key="secret",
        base_url="https://example.invalid/v1",
        dsh_root=dsh_root,
        dsh_bin=dsh,
        node_bin=node,
        host_environment={},
    )
    before = backend.runtime_identity()
    backend.plugin_bundle.write_text("export default function changed() {}\n")
    after = backend.runtime_identity()

    assert before["plugin_bundle_sha256"] != after["plugin_bundle_sha256"]
    assert before["profile_sha256"] == after["profile_sha256"]


def test_component_runner_uses_dsh_by_default(monkeypatch, tmp_path):
    import docker

    monkeypatch.delenv("AGENT_BACKEND", raising=False)
    monkeypatch.setattr(docker, "from_env", lambda: object())
    runner = ComponentAgentRunner(
        model="fixture-model",
        api_key="secret",
        base_url="https://example.invalid/v1",
        repository_root=tmp_path,
    )

    assert runner.backend_name == "dsh"
    assert isinstance(runner.backend, DshHeadlessBackend)
    assert "controlled_bash" in runner._effective_system_prompt("extraction")
