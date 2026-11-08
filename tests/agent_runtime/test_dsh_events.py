import json

from component_method.component_build.cache.review import observed_dependencies
from component_method.agent_runtime.events import result_from_dsh_events


def _write_jsonl(path, events):
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def test_dsh_events_require_mechanical_file_validation(tmp_path):
    events = tmp_path / "dsh_events.jsonl"
    validated = tmp_path / "validated_submission.json"
    _write_jsonl(
        events,
        [
            {"type": "session", "sessionId": "session-fixture", "cwd": "/runtime"},
            {"type": "status", "phase": "turn_start", "turn": 1},
            {
                "type": "tool_call",
                "callId": "call-1",
                "tool": "controlled_bash",
                "input": {"command": "rg -n symbol .", "cwd": "/testbed"},
            },
            {
                "type": "tool_result",
                "callId": "call-1",
                "status": "completed",
                "result": "exit_code=0",
            },
            {"type": "text", "text": "done"},
            {
                "type": "status",
                "phase": "step_end",
                "turn": 1,
                "step": 1,
                "usage": {"inputTokens": 12, "outputTokens": 4},
            },
            {
                "type": "status",
                "phase": "turn_end",
                "turn": 1,
                "reason": {"kind": "completed"},
            },
            {
                "type": "final",
                "sessionId": "session-fixture",
                "reason": {"kind": "completed"},
                "text": "done",
            },
        ],
    )
    validated.write_text(
        json.dumps(
            {
                "validated": True,
                "transport": "files",
                "role": "extraction",
                "container_name": "fixture-container",
                "checker_exit_code": 0,
            }
        ),
        encoding="utf-8",
    )

    result = result_from_dsh_events(
        events,
        return_code=0,
        validated_submission_path=validated,
        submission_mode="files",
        expected_role="extraction",
        expected_container="fixture-container",
        fallback_error="non-fatal diagnostic",
    )

    assert result.status == "Submitted"
    assert result.session_id == "session-fixture"
    assert result.completion_validated is True
    assert result.model_calls == 1
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert result.reported_cost_usd is None
    assert result.error is None
    assert result.tool_calls == [
        {
            "call_id": "call-1",
            "tool": "controlled_bash",
            "input": {"command": "rg -n symbol .", "cwd": "/testbed"},
            "status": "completed",
            "result": "exit_code=0",
        }
    ]


def test_dsh_final_text_without_validation_is_not_submission(tmp_path):
    events = tmp_path / "dsh_events.jsonl"
    _write_jsonl(
        events,
        [
            {"type": "session", "sessionId": "session-fixture"},
            {
                "type": "status",
                "phase": "step_end",
                "step": 1,
            },
            {
                "type": "final",
                "sessionId": "session-fixture",
                "reason": {"kind": "completed"},
                "text": "I submitted the files",
            },
        ],
    )

    result = result_from_dsh_events(
        events,
        return_code=0,
        validated_submission_path=tmp_path / "missing.json",
        submission_mode="files",
        expected_role="review",
        expected_container="fixture-container",
    )

    assert result.status == "NoValidatedSubmission"
    assert result.completion_validated is False
    assert result.input_tokens is None
    assert result.output_tokens is None


def test_dsh_events_accept_mechanically_validated_patch_submission(tmp_path):
    events = tmp_path / "dsh_events.jsonl"
    validated = tmp_path / "validated_submission.json"
    _write_jsonl(
        events,
        [
            {"type": "session", "sessionId": "session-patch"},
            {
                "type": "final",
                "sessionId": "session-patch",
                "reason": {"kind": "completed"},
                "text": '{"transport":"patch"}',
            },
        ],
    )
    validated.write_text(
        json.dumps(
            {
                "validated": True,
                "transport": "patch",
                "role": "task",
                "container_name": "task-container",
                "checker_exit_code": 0,
            }
        ),
        encoding="utf-8",
    )

    result = result_from_dsh_events(
        events,
        return_code=0,
        validated_submission_path=validated,
        submission_mode="patch",
        expected_role="task",
        expected_container="task-container",
    )

    assert result.status == "Submitted"
    assert result.completion_validated is True


def test_dsh_none_mode_cannot_be_promoted_by_a_validation_record(tmp_path):
    events = tmp_path / "dsh_events.jsonl"
    validated = tmp_path / "validated_submission.json"
    _write_jsonl(
        events,
        [
            {"type": "session", "sessionId": "session-none"},
            {
                "type": "final",
                "sessionId": "session-none",
                "reason": {"kind": "completed"},
                "text": "done",
            },
        ],
    )
    validated.write_text(
        json.dumps(
            {
                "validated": True,
                "transport": "none",
                "role": "task",
                "container_name": "task-container",
                "checker_exit_code": 0,
            }
        ),
        encoding="utf-8",
    )

    result = result_from_dsh_events(
        events,
        return_code=0,
        validated_submission_path=validated,
        submission_mode="none",
        expected_role="task",
        expected_container="task-container",
    )

    assert result.status == "AgentProcessError"
    assert result.completion_validated is False


def test_unknown_dsh_event_fails_closed(tmp_path):
    events = tmp_path / "dsh_events.jsonl"
    _write_jsonl(events, [{"type": "future_event", "value": 1}])

    result = result_from_dsh_events(
        events,
        return_code=0,
        validated_submission_path=tmp_path / "missing.json",
        submission_mode="files",
        expected_role="extraction",
        expected_container="fixture-container",
    )

    assert result.status == "AgentProcessError"
    assert "unknown DSH event type" in result.error


def test_missing_resume_session_maps_to_resume_error(tmp_path):
    events = tmp_path / "dsh_events.jsonl"
    _write_jsonl(
        events,
        [{"type": "error", "message": 'session "missing" does not exist'}],
    )

    result = result_from_dsh_events(
        events,
        return_code=1,
        validated_submission_path=tmp_path / "missing.json",
        submission_mode="files",
        expected_role="extraction",
        expected_container="fixture-container",
        resume_requested=True,
    )

    assert result.status == "ResumeError"
    assert result.completion_validated is False


def test_normalized_dsh_tool_calls_drive_dependency_audit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("VALUE = 1\n")
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(
        json.dumps(
            {
                "messages": [],
                "tool_calls": [
                    {
                        "tool": "controlled_bash",
                        "input": {"command": "sed -n '1,20p' module.py"},
                    }
                ],
            }
        )
    )

    assert observed_dependencies(trajectory, repo) == {
        "files": ["module.py"],
        "search_scopes": [],
    }
