"""Completion-marker compatibility for mini-swe-agent environments."""

from __future__ import annotations

from typing import Any

from minisweagent.agents.default import Submitted


COMPLETION_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def is_completion(output: dict[str, Any]) -> bool:
    lines = output.get("output", "").lstrip().splitlines()
    return bool(
        lines
        and lines[0].strip() == COMPLETION_MARKER
        and output.get("returncode") == 0
    )


def raise_if_completed(output: dict[str, Any]) -> None:
    """Raise the agent's terminal exception for a valid completion payload."""
    if not is_completion(output):
        return
    lines = output.get("output", "").lstrip().splitlines(keepends=True)
    submission = "".join(lines[1:]).strip()
    if not submission:
        output["output"] = (
            "The submission was empty because the command printed only the completion line. "
            "Submit again with the completion line and the complete result after it "
            "in the same shell command."
        )
        output["returncode"] = 1
        return
    raise Submitted(submission)
