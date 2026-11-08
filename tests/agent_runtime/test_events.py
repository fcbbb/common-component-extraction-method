import json

from component_method.agent_runtime.events import result_from_trajectory


def test_legacy_trajectory_is_normalized_without_inventing_usage(tmp_path):
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "inspect",
                        "extra": {"actions": [{"command": "rg -n symbol ."}]},
                    },
                    {
                        "role": "exit",
                        "content": "fallback",
                        "extra": {"submission": '{"transport":"files"}'},
                    },
                ],
                "info": {
                    "exit_status": "Submitted",
                    "model_stats": {"api_calls": 2, "instance_cost": None},
                },
            }
        ),
        encoding="utf-8",
    )
    result = result_from_trajectory(
        trajectory,
        return_code=0,
        session_id="session",
    )
    assert result.status == "Submitted"
    assert result.final_output == '{"transport":"files"}'
    assert result.model_calls == 2
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.reported_cost_usd is None
    assert result.tool_calls == [
        {"tool": "bash", "command": "rg -n symbol .", "message_index": 0}
    ]


def test_missing_trajectory_fails_closed(tmp_path):
    result = result_from_trajectory(
        tmp_path / "missing.json",
        return_code=0,
        session_id=None,
    )
    assert result.status == "NoValidatedSubmission"
    assert result.completion_validated is False
    assert result.error == "agent process produced no trajectory"


def test_nonzero_process_cannot_claim_submitted(tmp_path):
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(
        json.dumps({"messages": [], "info": {"exit_status": "Submitted"}}),
        encoding="utf-8",
    )
    result = result_from_trajectory(
        trajectory,
        return_code=7,
        session_id="session",
    )
    assert result.status == "AgentProcessError"
    assert result.completion_validated is False
