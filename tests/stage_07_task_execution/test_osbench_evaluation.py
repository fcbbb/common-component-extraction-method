"""OS-Bench evaluator adapter without Docker or model calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from component_method.task_execution.core import osbench_evaluation


PARSER_ALL_PASS = """
def parser(log):
    return {"A.test": "pass", "B.test": "pass"}
"""


def task(parser_source: str | None = PARSER_ALL_PASS) -> dict:
    install = {
        "rebuild_cmd": ["cmake --build build"],
        "test_cmd": ["ctest --test-dir build --output-on-failure"],
        "print_cmd": ["cat build/report.xml"],
    }
    if parser_source is not None:
        install["log_parser_source"] = parser_source
    return {
        "instance_id": "owner__repo-1__cpp__linux__abc123",
        "repo": "owner/repo",
        "base_commit": "a" * 40,
        "image_name": "example/osbench:task",
        "FAIL_TO_PASS": ["A.test"],
        "PASS_TO_PASS": ["B.test"],
        "test_patch": "",
        "install_config": install,
        "task_type": "cross_platform_migration",
    }


def install_fakes(monkeypatch, log: str, *, returncode: int = 0):
    captured = {}

    class Images:
        def get(self, name):
            captured["image_name"] = name
            return SimpleNamespace(id="sha256:" + "b" * 64)

    class Client:
        images = Images()

    def fake_run(arguments, **kwargs):
        if arguments[:2] == ["docker", "run"]:
            captured["run_args"] = arguments
            handle = kwargs.get("stdout")
            if handle is not None:
                handle.write(log)
            return SimpleNamespace(returncode=returncode)
        if arguments[:2] == ["docker", "rm"]:
            return SimpleNamespace(returncode=0)
        raise AssertionError(f"unexpected subprocess call: {arguments}")

    monkeypatch.setattr(osbench_evaluation.docker, "from_env", lambda: Client())
    monkeypatch.setattr(osbench_evaluation.subprocess, "run", fake_run)
    return captured


def status_log(rebuild=0, test=0, print_status=0) -> str:
    return "\n".join(
        [
            "test output line",
            f"{osbench_evaluation.STATUS_MARKER}REBUILD_STATUS={rebuild}",
            f"{osbench_evaluation.STATUS_MARKER}TEST_STATUS={test}",
            f"{osbench_evaluation.STATUS_MARKER}PRINT_STATUS={print_status}",
        ]
    ) + "\n"


def test_osbench_detection():
    assert osbench_evaluation.is_osbench_task(task())
    assert not osbench_evaluation.is_osbench_task(
        {"install_config": {"test_cmd": ["pytest"]}}
    )


def test_osbench_evaluator_runs_rebuild_test_print_and_passes(tmp_path, monkeypatch):
    captured = install_fakes(monkeypatch, status_log())
    result = osbench_evaluation.evaluate_osbench(
        task(),
        "diff --git a/a b/a\n",
        tmp_path,
        normalize_test_name=lambda value: value.strip(),
    )
    assert result["evaluated"] is True
    assert result["passed_match"] is True
    assert result["required_tests_passed"] is True
    assert result["F2P_passed"] == 1
    assert result["P2P_passed"] == 1
    assert result["rebuild_exit_code"] == 0
    assert result["test_exit_code"] == 0
    assert result["print_exit_code"] == 0
    script = captured["run_args"][-1]
    assert "cmake --build build" in script
    assert "ctest --test-dir build" in script
    assert "cat build/report.xml" in script
    assert "source.patch" in script
    assert "test.patch" not in script
    assert "git reset --hard HEAD" in script


def test_osbench_evaluator_counts_fail_skip_and_missing(tmp_path, monkeypatch):
    install_fakes(
        monkeypatch,
        status_log(),
    )
    raw_parser = """
def parser(log):
    return {"A.test": "fail", "B.test": "skip"}
"""
    result = osbench_evaluation.evaluate_osbench(
        task(raw_parser),
        "",
        tmp_path,
        normalize_test_name=lambda value: value.strip(),
    )
    assert result["passed_match"] is False
    assert result["required_tests_passed"] is False
    assert result["F2P_passed"] == 0
    assert result["F2P_failed"] == 1
    assert result["P2P_passed"] == 0
    assert result["missing_required"] == ["A.test", "B.test"]


def test_osbench_evaluator_reports_rebuild_failure(tmp_path, monkeypatch):
    install_fakes(monkeypatch, status_log(rebuild=2, test=0))
    result = osbench_evaluation.evaluate_osbench(
        task(),
        "",
        tmp_path,
        normalize_test_name=lambda value: value.strip(),
    )
    assert result["rebuild_exit_code"] == 2
    assert "rebuild command failed" in result["error"]
    assert result["passed_match"] is True


def test_osbench_evaluator_rejects_missing_parser(tmp_path, monkeypatch):
    install_fakes(monkeypatch, status_log())
    result = osbench_evaluation.evaluate_osbench(
        task(parser_source=None),
        "",
        tmp_path,
        normalize_test_name=lambda value: value.strip(),
    )
    assert result["evaluated"] is False
    assert "log_parser_source" in result["error"]
    assert result["passed_match"] is False


def test_osbench_evaluator_supports_excluded_tests(tmp_path, monkeypatch):
    install_fakes(monkeypatch, status_log())
    parser = """
def parser(log):
    return {"A.test": "pass"}
"""
    result = osbench_evaluation.evaluate_osbench(
        task(parser),
        "",
        tmp_path,
        normalize_test_name=lambda value: value.strip(),
        excluded=["B.test"],
    )
    assert result["F2P_passed"] == 1
    assert result["P2P_total"] == 0
    assert result["passed_match"] is True


def test_osbench_evaluator_image_mismatch_is_rejected(tmp_path, monkeypatch):
    install_fakes(monkeypatch, status_log())
    with pytest.raises(AssertionError):
        osbench_evaluation.evaluate_osbench(
            task(),
            "",
            tmp_path,
            normalize_test_name=lambda value: value.strip(),
            expected_image_id="sha256:" + "c" * 64,
        )