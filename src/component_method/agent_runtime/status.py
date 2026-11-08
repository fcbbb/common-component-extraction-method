"""Framework-independent agent run statuses."""

from __future__ import annotations


SUBMITTED = "Submitted"
LIMITS_EXCEEDED = "LimitsExceeded"
TIMEOUT = "Timeout"
STOPPED_BY_USER = "StoppedByUser"
AGENT_PROCESS_ERROR = "AgentProcessError"
TASK_ENVIRONMENT_LOST = "TaskEnvironmentLost"
RESUME_ERROR = "ResumeError"
NO_VALIDATED_SUBMISSION = "NoValidatedSubmission"


_KNOWN_STATUSES = {
    SUBMITTED,
    LIMITS_EXCEEDED,
    TIMEOUT,
    STOPPED_BY_USER,
    AGENT_PROCESS_ERROR,
    TASK_ENVIRONMENT_LOST,
    RESUME_ERROR,
    NO_VALIDATED_SUBMISSION,
}


def normalize_status(exit_status: str | None, *, return_code: int | None) -> str:
    """Map backend-specific termination details to the public status contract."""
    status = str(exit_status or "").strip()
    if status == SUBMITTED and return_code not in (None, 0):
        return AGENT_PROCESS_ERROR
    if status in _KNOWN_STATUSES:
        return status
    if status in {"StepLimitExceeded", "StepLimitReached", "CostLimitExceeded"}:
        return LIMITS_EXCEEDED
    if status in {"KeyboardInterrupt", "Interrupted"}:
        return STOPPED_BY_USER
    if status in {"ContainerNotFound", "EnvironmentLost"}:
        return TASK_ENVIRONMENT_LOST
    if status in {"InvalidResume", "SessionNotFound"}:
        return RESUME_ERROR
    if return_code not in (None, 0):
        return AGENT_PROCESS_ERROR
    return NO_VALIDATED_SUBMISSION
