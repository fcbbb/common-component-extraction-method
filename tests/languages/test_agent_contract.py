"""Prompt and validator must describe the same agent output."""

import json
from pathlib import Path
from types import SimpleNamespace

from component_method.component_build import submission
from component_method.languages.agent_contract import (
    ARTIFACT_FILE_ROLES,
    ARTIFACT_REVIEW_STATUSES,
    EXTRACTION_COMPONENT_FIELDS,
    PROTOCOL_CONTRACT_FIELDS,
    PROTOCOL_CONTRACT_ISSUE_SEVERITIES,
    PROTOCOL_CONTRACT_ISSUE_STATUSES,
    PROTOCOL_CONTRACT_REVIEW_STATUSES,
    REVIEW_STATUSES,
    SMOKE_CASE_ID_PATTERN,
    annotate_component_members,
    extraction_output_schema,
    normalize_review_result,
    review_output_schema,
)
from component_method.languages.prompts import extraction_prompt, review_prompt

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "schemas" / "protocol_contract_schema.json"


class FakeBackend:
    language_id = "cpp"
    backend_id = "cpp@1"

    def agent_instructions(self, role):
        return "backend instructions"

    def extract_units(self, file_id, source):
        return self.units


def test_review_prompt_renders_the_schema_the_validator_checks():
    prompt = review_prompt({"members": []}, FakeBackend())
    schema = review_output_schema(FakeBackend())
    for field in (
        "status", "reason", "confirmed_members", "evidence", "artifact_review",
        "protocol_contract_review", "smoke_test", "validation_dependencies",
    ):
        assert f'"{field}"' in prompt
        assert field in schema
    member = schema["confirmed_members"][0]
    assert {"file_id", "unit_key", "unit_id"} <= set(member)
    assert set(schema["protocol_contract_review"]["reviewed_fields"]) == set(PROTOCOL_CONTRACT_FIELDS)
    issue = schema["protocol_contract_review"]["field_issues"][0]
    assert {"field", "status", "severity", "issue", "evidence"} <= set(issue)
    assert issue["status"].split("|") == list(PROTOCOL_CONTRACT_ISSUE_STATUSES)
    assert issue["severity"].split("|") == list(PROTOCOL_CONTRACT_ISSUE_SEVERITIES)
    assert schema["protocol_contract_review"]["status"].split("|") == list(
        PROTOCOL_CONTRACT_REVIEW_STATUSES
    )
    assert schema["status"].split("|") == list(REVIEW_STATUSES)
    assert schema["artifact_review"]["status"].split("|") == list(ARTIFACT_REVIEW_STATUSES)
    case = schema["smoke_test"]["cases"][0]
    assert case["expected_paths"] == [{"entrypoint_id": "declared entrypoint id"}]
    assert case["files"][0]["role"] in ARTIFACT_FILE_ROLES


def test_extraction_prompt_renders_the_schema_the_validator_requires():
    prompt = extraction_prompt(SimpleNamespace(context={}), FakeBackend())
    schema = extraction_output_schema(FakeBackend())
    component = schema["components"][0]
    assert set(EXTRACTION_COMPONENT_FIELDS) <= set(component)
    for field in EXTRACTION_COMPONENT_FIELDS:
        assert f'"{field}"' in prompt
    assert set(component["protocol_contract"]) == set(PROTOCOL_CONTRACT_FIELDS)
    assert component["artifact"]["files"][0]["role"] == "header|source|smoke"


def test_submission_checker_uses_the_same_protocol_fields():
    # ``submission.py`` is copied into agent containers without this package,
    # so its constants are declared locally.  Keep the copy in sync.
    assert set(submission.PROTOCOL_CONTRACT_FIELDS) == set(PROTOCOL_CONTRACT_FIELDS)


def test_extraction_validator_schema_matches_the_shared_protocol_fields():
    # ``validate_protocol_contracts`` reads this file rather than importing the
    # constants, so the JSON schema is a third copy that has to stay aligned.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["required_fields"]) == set(PROTOCOL_CONTRACT_FIELDS)
    assert set(schema["consumer_required_fields"]) == {"file_id", "unit_id", "role"}
    assert schema["minimum_consumer_count"] == 2
    assert set(schema["reuse_modes"]) == {"stable_entrypoint", "reference_pattern"}


def test_review_prompt_uses_the_shared_smoke_case_id_pattern():
    prompt = review_prompt({"members": []}, FakeBackend())
    assert SMOKE_CASE_ID_PATTERN in prompt
    assert SMOKE_CASE_ID_PATTERN in review_output_schema(FakeBackend())["smoke_test"]["cases"][0]["case_id"]


def test_annotate_component_members_resolves_names_for_the_reviewer(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.c").write_text("x\n")

    class Backend(FakeBackend):
        units = [SimpleNamespace(
            unit_key="key-1", qualified_name="ns::f", display_name="f",
            span=SimpleNamespace(start_line=1, end_line=3),
        )]

    component = {"members": [{"file_id": "src/a.c", "unit_key": "key-1"}]}
    annotated = annotate_component_members(component, Backend(), tmp_path)
    assert annotated["members"][0] == {
        "file_id": "src/a.c", "unit_key": "key-1",
        "name": "f", "qualified_name": "ns::f", "line_start": 1, "line_end": 3,
    }
    # The canonical component is not mutated.
    assert component["members"][0] == {"file_id": "src/a.c", "unit_key": "key-1"}


def test_review_member_name_and_lines_normalize_to_unit_key(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.c").write_text("x\n")

    class Backend(FakeBackend):
        units = [SimpleNamespace(
            unit_key="key-1", qualified_name="ns::f", display_name="f",
            span=SimpleNamespace(start_line=1, end_line=3),
        )]

    component = {"members": [{"file_id": "src/a.c", "unit_key": "key-1"}]}
    review = {
        "confirmed_members": [
            {"file_id": "src/a.c", "member": "f", "line_start": 1, "line_end": 3},
        ],
    }
    normalized = normalize_review_result(
        review, component=component, backend=Backend(), repository_root=tmp_path,
    )
    assert normalized["confirmed_members"] == [{
        "file_id": "src/a.c", "member": "f", "line_start": 1, "line_end": 3,
        "unit_key": "key-1", "unit_id": "key-1",
    }]


def test_review_member_outside_the_proposed_set_is_not_normalized(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.c").write_text("x\n")

    class Backend(FakeBackend):
        units = [SimpleNamespace(
            unit_key="other", qualified_name="ns::other", display_name="other",
            span=SimpleNamespace(start_line=1, end_line=3),
        )]

    component = {"members": [{"file_id": "src/a.c", "unit_key": "key-1"}]}
    review = {"confirmed_members": [{"file_id": "src/a.c", "member": "other",
                                     "line_start": 1, "line_end": 3}]}
    normalized = normalize_review_result(
        review, component=component, backend=Backend(), repository_root=tmp_path,
    )
    assert normalized["confirmed_members"][0].get("unit_key") is None


def test_review_expected_paths_keyed_by_entrypoint_normalize_to_entrypoint_id(tmp_path):
    # The contract is [{"entrypoint_id": "<declared id>"}].  A reviewer that
    # writes {"<declared id>": "<expected behavior>"} states the same intent;
    # grounding it here keeps the strict shape check meaningful.
    component = {"artifact": {"entrypoints": [
        {"qualified_name": "ns::f"}, {"qualified_name": "ns::g"},
    ]}}
    review = {"smoke_test": {"status": "ready", "cases": [{
        "case_id": "case-1",
        "entrypoint_id": "ns::f",
        "expected_paths": [
            {"ns::f": "returns 1"},
            {"entrypoint_id": "ns::g", "note": "extra"},
            {"ns::undeclared": "left for the validator"},
        ],
    }]}}
    normalized = normalize_review_result(
        review, component=component, backend=FakeBackend(), repository_root=tmp_path,
    )
    assert normalized["smoke_test"]["cases"][0]["expected_paths"] == [
        {"entrypoint_id": "ns::f"},
        {"entrypoint_id": "ns::g"},
        {"ns::undeclared": "left for the validator"},
    ]