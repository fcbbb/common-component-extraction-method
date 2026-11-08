"""Stable contracts shared by workflow stages and agent backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SubmissionMode = Literal["files", "patch", "none"]


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    role: str
    model: str
    system_prompt: str
    task_prompt: str
    output_dir: Path
    container_name: str
    container_cwd: str
    command_timeout_seconds: int
    total_timeout_seconds: int | None
    step_limit: int | None
    submission_mode: SubmissionMode
    submission_role: str | None
    resume_session_id: str | None = None
    submission_checker_command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    session_id: str | None
    final_output: str
    messages: list[dict]
    tool_calls: list[dict]
    model_calls: int
    input_tokens: int | None
    output_tokens: int | None
    reported_cost_usd: float | None
    completion_validated: bool
    error: str | None
