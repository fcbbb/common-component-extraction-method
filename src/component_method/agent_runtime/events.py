"""Normalize backend trajectories into the stable agent result contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import AgentRunResult
from .status import (
    AGENT_PROCESS_ERROR,
    LIMITS_EXCEEDED,
    NO_VALIDATED_SUBMISSION,
    RESUME_ERROR,
    STOPPED_BY_USER,
    SUBMITTED,
    TASK_ENVIRONMENT_LOST,
    TIMEOUT,
    normalize_status,
)


DSH_EVENT_TYPES = {
    "session",
    "status",
    "text",
    "thinking",
    "tool_call",
    "tool_result",
    "final",
    "error",
}


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _usage_value(stats: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = _optional_int(stats.get(name))
        if value is not None:
            return value
    return None


def normalized_tool_calls(messages: list[dict]) -> list[dict]:
    """Extract tool calls without exposing consumers to backend message details."""
    calls: list[dict] = []
    for message_index, message in enumerate(messages):
        direct = message.get("tool_calls")
        if isinstance(direct, list):
            for call in direct:
                if isinstance(call, dict):
                    calls.append({**call, "message_index": message_index})
        extra = message.get("extra")
        actions = extra.get("actions") if isinstance(extra, dict) else None
        if isinstance(actions, list):
            for action in actions:
                if isinstance(action, dict):
                    calls.append({"tool": "bash", **action, "message_index": message_index})
    return calls


def result_from_trajectory(
    trajectory_path: Path,
    *,
    return_code: int | None,
    session_id: str | None,
    fallback_error: str | None = None,
) -> AgentRunResult:
    """Read a legacy trajectory and return normalized fields."""
    if not trajectory_path.is_file():
        status = normalize_status(None, return_code=return_code)
        return AgentRunResult(
            status=status,
            session_id=session_id,
            final_output="",
            messages=[],
            tool_calls=[],
            model_calls=0,
            input_tokens=None,
            output_tokens=None,
            reported_cost_usd=None,
            completion_validated=False,
            error=fallback_error or "agent process produced no trajectory",
        )
    try:
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        status = normalize_status(None, return_code=return_code)
        return AgentRunResult(
            status=status,
            session_id=session_id,
            final_output="",
            messages=[],
            tool_calls=[],
            model_calls=0,
            input_tokens=None,
            output_tokens=None,
            reported_cost_usd=None,
            completion_validated=False,
            error=fallback_error or f"invalid agent trajectory: {exc}",
        )

    info = trajectory.get("info") if isinstance(trajectory, dict) else {}
    if not isinstance(info, dict):
        info = {}
    raw_messages = trajectory.get("messages") if isinstance(trajectory, dict) else []
    messages = (
        [message for message in raw_messages if isinstance(message, dict)]
        if isinstance(raw_messages, list)
        else []
    )
    stats = info.get("model_stats")
    if not isinstance(stats, dict):
        stats = {}
    raw_status = str(info.get("exit_status") or "")
    final_output = str(info.get("submission") or "")
    if not final_output:
        for message in reversed(messages):
            if message.get("role") == "exit":
                extra = message.get("extra")
                final_output = str(
                    (extra.get("submission") if isinstance(extra, dict) else None)
                    or message.get("content")
                    or ""
                )
                break
    if not final_output:
        final_output = str(info.get("result") or "")
    status = normalize_status(raw_status, return_code=return_code)
    error = None
    if status != "Submitted":
        error = fallback_error or str(info.get("result") or raw_status or status)
    return AgentRunResult(
        status=status,
        session_id=session_id,
        final_output=final_output,
        messages=messages,
        tool_calls=normalized_tool_calls(messages),
        model_calls=_optional_int(stats.get("api_calls")) or 0,
        input_tokens=_usage_value(stats, "input_tokens", "prompt_tokens"),
        output_tokens=_usage_value(stats, "output_tokens", "completion_tokens"),
        reported_cost_usd=_optional_float(stats.get("instance_cost")),
        completion_validated=status == "Submitted",
        error=error,
    )


def _dsh_failure_result(
    message: str,
    *,
    session_id: str | None = None,
    status: str = AGENT_PROCESS_ERROR,
) -> AgentRunResult:
    return AgentRunResult(
        status=status,
        session_id=session_id,
        final_output="",
        messages=[],
        tool_calls=[],
        model_calls=0,
        input_tokens=None,
        output_tokens=None,
        reported_cost_usd=None,
        completion_validated=False,
        error=message,
    )


def read_dsh_events(events_path: Path) -> list[dict[str, Any]]:
    """Read DSH JSONL and reject malformed or unknown event records."""
    events: list[dict[str, Any]] = []
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"could not read DSH events: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid DSH event JSON on line {line_number}: {exc}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"DSH event on line {line_number} is not an object")
        event_type = event.get("type")
        if event_type not in DSH_EVENT_TYPES:
            raise ValueError(
                f"unknown DSH event type on line {line_number}: {event_type!r}"
            )
        events.append(event)
    if not events:
        raise ValueError("DSH process produced no JSON events")
    return events


def _validated_submission_record(
    path: Path,
    *,
    expected_transport: str,
    expected_role: str | None,
    expected_container: str | None,
) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"invalid validated submission record: {exc}"
    if not isinstance(record, dict):
        return False, "validated submission record is not an object"
    if record.get("validated") is not True or record.get("transport") != expected_transport:
        return False, (
            "validated submission record does not confirm the requested "
            f"{expected_transport} submission"
        )
    if expected_role is not None and record.get("role") != expected_role:
        return False, "validated submission role does not match the request"
    if expected_container is not None and record.get("container_name") != expected_container:
        return False, "validated submission container does not match the request"
    if record.get("checker_exit_code") != 0:
        return False, "validated submission checker did not report success"
    return True, None


def _dsh_error_status(message: str, *, resume_requested: bool) -> str:
    lowered = message.lower()
    if resume_requested and any(
        marker in lowered
        for marker in (
            "does not exist",
            "cannot be adopted",
            "cannot own an exclusive run interval",
            "requires the sessionpersistence",
            "requires the sessionquery",
        )
    ):
        return RESUME_ERROR
    if "taskenvironmentlost" in lowered or "container is not running" in lowered:
        return TASK_ENVIRONMENT_LOST
    if "stopped by user" in lowered or "keyboardinterrupt" in lowered:
        return STOPPED_BY_USER
    return AGENT_PROCESS_ERROR


def result_from_dsh_events(
    events_path: Path,
    *,
    return_code: int | None,
    validated_submission_path: Path,
    submission_mode: str,
    expected_role: str | None,
    expected_container: str | None,
    resume_requested: bool = False,
    timed_out: bool = False,
    step_limited: bool = False,
    step_limit: int | None = None,
    fallback_error: str | None = None,
) -> AgentRunResult:
    """Normalize the bounded DSH headless JSON stream into the public contract."""
    try:
        events = read_dsh_events(events_path)
    except ValueError as exc:
        status = TIMEOUT if timed_out else AGENT_PROCESS_ERROR
        return _dsh_failure_result(fallback_error or str(exc), status=status)

    session_id: str | None = None
    messages: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    call_indexes: dict[str, int] = {}
    final_output = ""
    final_reason: dict[str, Any] | None = None
    stream_errors: list[str] = []
    model_calls = 0
    usage_complete = True
    usage_seen = False
    input_tokens = 0
    output_tokens = 0
    max_step = 0

    for event in events:
        event_type = event["type"]
        if event_type == "session":
            current = event.get("sessionId")
            if not isinstance(current, str) or not current:
                stream_errors.append("DSH session event has no sessionId")
            elif session_id is not None and current != session_id:
                stream_errors.append("DSH event stream contains conflicting session IDs")
            else:
                session_id = current
        elif event_type in {"text", "thinking"}:
            text = event.get("text")
            if not isinstance(text, str):
                stream_errors.append(f"DSH {event_type} event has no text")
            else:
                messages.append(
                    {"role": "assistant", "content": text, "kind": event_type}
                )
        elif event_type == "tool_call":
            call_id = event.get("callId")
            tool = event.get("tool")
            if not isinstance(call_id, str) or not isinstance(tool, str):
                stream_errors.append("DSH tool_call event is missing callId or tool")
            else:
                call_indexes[call_id] = len(tool_calls)
                tool_calls.append(
                    {
                        "call_id": call_id,
                        "tool": tool,
                        "input": event.get("input"),
                    }
                )
        elif event_type == "tool_result":
            call_id = event.get("callId")
            if not isinstance(call_id, str) or call_id not in call_indexes:
                stream_errors.append("DSH tool_result has no matching tool_call")
            else:
                call = tool_calls[call_indexes[call_id]]
                call["status"] = event.get("status")
                call["result"] = event.get("result")
                if "error" in event:
                    call["error"] = event["error"]
        elif event_type == "status":
            phase = event.get("phase")
            if not isinstance(phase, str):
                stream_errors.append("DSH status event has no phase")
                continue
            step = _optional_int(event.get("step"))
            if step is not None:
                max_step = max(max_step, step)
            if phase == "step_end":
                model_calls += 1
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    usage_complete = False
                else:
                    prompt = _optional_int(usage.get("inputTokens"))
                    completion = _optional_int(usage.get("outputTokens"))
                    if prompt is None or completion is None:
                        usage_complete = False
                    else:
                        usage_seen = True
                        input_tokens += prompt
                        output_tokens += completion
            if phase == "turn_end" and isinstance(event.get("reason"), dict):
                final_reason = event["reason"]
        elif event_type == "final":
            current = event.get("sessionId")
            if not isinstance(current, str) or not current:
                stream_errors.append("DSH final event has no sessionId")
            elif session_id is not None and current != session_id:
                stream_errors.append("DSH final event sessionId does not match")
            else:
                session_id = current
            text = event.get("text")
            if not isinstance(text, str):
                stream_errors.append("DSH final event has no text")
            else:
                final_output = text
            reason = event.get("reason")
            if reason is not None and not isinstance(reason, dict):
                stream_errors.append("DSH final reason is not an object or null")
            elif isinstance(reason, dict):
                final_reason = reason
        elif event_type == "error":
            message = event.get("message")
            stream_errors.append(
                message if isinstance(message, str) else "DSH emitted an error event"
            )

    final_events = [event for event in events if event["type"] == "final"]
    if len(final_events) != 1 and not timed_out and not step_limited:
        stream_errors.append(f"DSH event stream contains {len(final_events)} final events")
    if submission_mode in {"files", "patch"}:
        completion_validated, validation_error = _validated_submission_record(
            validated_submission_path,
            expected_transport=submission_mode,
            expected_role=expected_role,
            expected_container=expected_container,
        )
    else:
        completion_validated = False
        validation_error = (
            "validated submission record is incompatible with submission mode"
            if validated_submission_path.is_file()
            else None
        )
    if validation_error:
        stream_errors.append(validation_error)

    stream_error_message = "; ".join(stream_errors) or None
    if timed_out:
        status = TIMEOUT
        completion_validated = False
        error_message = fallback_error or stream_error_message or "DSH process timed out"
    elif stream_errors or (
        return_code not in (None, 0) and not step_limited
    ):
        error_message = "; ".join(
            value for value in (fallback_error, stream_error_message) if value
        ) or "DSH process failed"
        status = _dsh_error_status(error_message or "DSH process failed", resume_requested=resume_requested)
        completion_validated = False
    elif completion_validated:
        status = SUBMITTED
        error_message = None
    elif step_limited:
        status = LIMITS_EXCEEDED
        error_message = fallback_error
    elif step_limit is not None and max_step >= step_limit:
        status = LIMITS_EXCEEDED
        error_message = None
    else:
        status = NO_VALIDATED_SUBMISSION
        error_message = None

    reason_kind = final_reason.get("kind") if isinstance(final_reason, dict) else None
    if status == NO_VALIDATED_SUBMISSION and reason_kind in {"aborted", "interrupted"}:
        status = STOPPED_BY_USER
    elif status == NO_VALIDATED_SUBMISSION and reason_kind == "max-tokens":
        status = LIMITS_EXCEEDED
    elif status == NO_VALIDATED_SUBMISSION and reason_kind == "error":
        status = AGENT_PROCESS_ERROR
    if status != SUBMITTED and error_message is None:
        error_message = str(final_reason or status)

    return AgentRunResult(
        status=status,
        session_id=session_id,
        final_output=final_output,
        messages=messages,
        tool_calls=tool_calls,
        model_calls=model_calls,
        input_tokens=input_tokens if usage_complete and usage_seen else None,
        output_tokens=output_tokens if usage_complete and usage_seen else None,
        reported_cost_usd=None,
        completion_validated=completion_validated,
        error=error_message,
    )
