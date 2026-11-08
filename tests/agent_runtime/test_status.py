import pytest

from component_method.agent_runtime.status import normalize_status


@pytest.mark.parametrize(
    ("exit_status", "return_code", "expected"),
    [
        ("Submitted", 0, "Submitted"),
        ("Submitted", 1, "AgentProcessError"),
        ("StepLimitExceeded", 1, "LimitsExceeded"),
        ("KeyboardInterrupt", 1, "StoppedByUser"),
        ("ContainerNotFound", 1, "TaskEnvironmentLost"),
        ("InvalidResume", 1, "ResumeError"),
        ("ValueError", 1, "AgentProcessError"),
        ("Finished", 0, "NoValidatedSubmission"),
    ],
)
def test_status_mapping(exit_status, return_code, expected):
    assert normalize_status(exit_status, return_code=return_code) == expected
