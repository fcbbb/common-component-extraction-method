"""Exercise actual file transport, syntax checking and result hydration."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from component_method.component_build import submission


def extraction(root):
    (root / "common.py").write_text("def make(value):\n    return value + 1\n")
    manifest = {"status": "ready", "components": [{
        "status": "draft_ready", "component_id": "make", "library": {"path": "common.py"},
        "entrypoints": [{"name": "make", "kind": "function", "purpose": "Increment."}],
    }]}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_extraction_collects_code_from_files_without_executing_it(tmp_path):
    original = extraction(tmp_path)
    source = "raise RuntimeError('must not execute')\ndef make(value):\n    return value + 1\n"
    (tmp_path / "common.py").write_text(source)
    result = submission.load_submission(tmp_path, "extraction")
    assert result["components"][0]["library"]["content"] == source
    assert json.loads((tmp_path / "manifest.json").read_text()) == original


def test_review_collects_each_test_from_its_own_file(tmp_path):
    (tmp_path / "cases").mkdir()
    source = "def run(common):\n    assert common.make(1) == 2\n    return True\n"
    (tmp_path / "cases/one.py").write_text(source)
    manifest = {"status": "confirmed", "smoke_test": {"status": "ready", "cases": [
        {"case_id": "one", "entrypoint": "make", "test_file": "cases/one.py", "sources": []}
    ]}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    result = submission.load_submission(tmp_path, "review")
    assert result["smoke_test"]["cases"][0]["test_py"] == source
    assert "test_file" not in result["smoke_test"]["cases"][0]


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/outside.py", "missing.py"])
def test_missing_or_outside_files_are_rejected(tmp_path, path):
    manifest = extraction(tmp_path)
    manifest["components"][0]["library"]["path"] = path
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        submission.load_submission(tmp_path, "extraction")


def test_symlink_in_a_parent_directory_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (outside / "code.py").write_text("def make(): return 1\n")
    manifest = extraction(tmp_path)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    manifest["components"][0]["library"]["path"] = "link/code.py"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="symlink"):
        submission.load_submission(tmp_path, "extraction")


def test_agent_can_fix_a_syntax_error_and_recheck_with_the_same_cli(tmp_path):
    extraction(tmp_path)
    command = [sys.executable, submission.__file__, "--role", "extraction", "--output", str(tmp_path)]
    (tmp_path / "common.py").write_text("def make(:\n")
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode == 1
    assert "Submission check failed" in failed.stdout
    invalid_submission = subprocess.run(command + ["--submit"], capture_output=True, text=True)
    assert invalid_submission.returncode == 1
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" not in invalid_submission.stdout
    (tmp_path / "common.py").write_text("def make(value): return value + 1\n")
    assert subprocess.run(command, capture_output=True).returncode == 0
    submitted = subprocess.run(command + ["--submit"], capture_output=True, text=True)
    assert submitted.stdout.strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


@pytest.mark.parametrize("content", ["{not-json", "[]", ""])
def test_invalid_manifest_fails_the_file_check(tmp_path, content):
    (tmp_path / "manifest.json").write_text(content)
    with pytest.raises(ValueError):
        submission.load_submission(tmp_path, "extraction")


def test_inline_source_is_not_accepted_as_a_new_file_submission(tmp_path):
    manifest = extraction(tmp_path)
    manifest["components"][0]["library"] = {"content": "def make(): return 1\n"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="library.path"):
        submission.load_submission(tmp_path, "extraction")


def test_metadata_only_no_component_and_rejected_review_can_submit(tmp_path):
    (tmp_path / "manifest.json").write_text('{"status":"no_component","components":[]}')
    assert submission.load_submission(tmp_path, "extraction")["components"] == []
    (tmp_path / "manifest.json").write_text('{"status":"rejected","reason":"Unsupported capability"}')
    assert submission.load_submission(tmp_path, "review")["status"] == "rejected"


def test_review_capability_format_is_checked_before_completion(tmp_path):
    manifest = {"status": "confirmed", "entrypoint_capabilities": [{
        "entrypoint": "make", "method": "", "availability": "unverified",
        "contract": "Increment", "example": "make(1)", "scope": "numbers", "case_ids": [],
    }]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reason"):
        submission.load_submission(tmp_path, "review")
    manifest["entrypoint_capabilities"][0]["reason"] = "Insufficient usage evidence"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert submission.load_submission(tmp_path, "review")["status"] == "confirmed"


def test_protocol_review_v2_shape_is_checked_before_completion(tmp_path):
    fields = sorted(submission.PROTOCOL_CONTRACT_FIELDS)
    issue = {
        "field": "extension_trigger",
        "status": "overstated",
        "severity": "blocking",
        "issue": "The trigger can cause an unnecessary implementation change.",
        "evidence": [{"file_id": "module.py", "line_start": 1, "line_end": 1, "claim": "Direct behavior."}],
    }
    manifest = {
        "status": "confirmed",
        "protocol_contract_review": {
            "schema_version": 2,
            "status": "needs_revision",
            "reason": "One blocking field.",
            "reviewed_fields": fields,
            "confirmed_fields": [field for field in fields if field != "extension_trigger"],
            "field_issues": [issue],
            "field_revisions": {},
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="exactly the blocking fields"):
        submission.load_submission(tmp_path, "review")

    manifest["protocol_contract_review"]["field_revisions"] = {
        "extension_trigger": "Check existing coverage before changing the implementation."
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert submission.load_submission(tmp_path, "review")["status"] == "confirmed"


def test_mounted_review_citations_reject_missing_files_and_line_overflow(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "module.py").write_text("first\nsecond\n")
    review = {
        "evidence": [{
            "file_id": "module.py", "line_start": 1, "line_end": 2, "claim": "Two lines."
        }]
    }
    submission._validate_mounted_review_citations(review, source)

    review["evidence"][0]["line_end"] = 3
    with pytest.raises(ValueError, match="exceeds the end"):
        submission._validate_mounted_review_citations(review, source)

    review["evidence"][0].update({"file_id": "missing.py", "line_end": 1})
    with pytest.raises(ValueError, match="does not resolve"):
        submission._validate_mounted_review_citations(review, source)
