"""Verify constrained component repair without model or Docker calls."""

from copy import deepcopy

import pytest

from component_method.component_build.repair.service import repair_component_with_agent
from component_method.component_build.submission import load_submission


class Repairer:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_workspace_agent(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.result)


def component(code="def normalize(value):\n    return value.strip().lower()\n"):
    return {
        "component_id": "normalize",
        "status": "draft_ready",
        "members": [{"file_id": "module.py", "unit_id": "function:normalize"}],
        "library": {"path": "components/normalize.py", "content": code},
        "entrypoints": [{"name": "normalize", "kind": "function", "purpose": "Normalize a label"}],
        "evidence": [
            {"file_id": "module.py", "line_start": 1, "line_end": 1, "claim": "Defines normalize."},
            {"file_id": "consumer.py", "line_start": 1, "line_end": 1, "claim": "Consumes labels."},
        ],
        "limitations": [],
    }


def contract():
    return {
        "capability_family": "normalizer",
        "semantic_domain": "Labels used for lookup.",
        "extension_trigger": "A new label source enters lookup.",
        "covered_variants": ["padded", "uppercase"],
        "downstream_guarantee": "Labels are lowercase without surrounding whitespace.",
        "consumers": [
            {"file_id": "module.py", "unit_id": "function:normalize", "role": "normalizes labels"},
            {"file_id": "consumer.py", "unit_id": "function:lookup", "role": "uses normalized labels"},
        ],
        "reuse_interface": {"mode": "stable_entrypoint", "value": "normalize"},
        "boundary": "Storage remains outside the component.",
    }


def test_protocol_repair_changes_only_allowed_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value.strip().lower()\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    original["protocol_contract"] = contract()
    revised = deepcopy(original["protocol_contract"])
    revised["extension_trigger"] = "First check whether the existing normalizer covers the new label source."
    runner = Repairer({
        "status": "repaired", "repair_target": "protocol_contract",
        "reason": "The trigger overstated the need for code changes.",
        "changes": ["extension_trigger: require a coverage check first"],
        "protocol_contract": revised,
    })
    result = repair_component_with_agent(
        runner, repo, original,
        {"repair_target": "protocol_contract", "allowed_protocol_fields": ["extension_trigger"]},
        tmp_path / "repair",
    )
    assert result["protocol_contract"] == revised
    assert runner.calls[0]["agent_role"] == "repair"


def test_protocol_repair_rejects_unrequested_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    original["protocol_contract"] = contract()
    revised = deepcopy(original["protocol_contract"])
    revised["extension_trigger"] = "Check coverage first."
    revised["boundary"] = "Changed without permission."
    with pytest.raises(ValueError, match="disallowed field: boundary"):
        repair_component_with_agent(
            Repairer({
                "status": "repaired", "repair_target": "protocol_contract", "reason": "Fixture",
                "changes": ["Changed trigger and boundary"], "protocol_contract": revised,
            }),
            repo, original,
            {"repair_target": "protocol_contract", "allowed_protocol_fields": ["extension_trigger"]},
            tmp_path / "repair",
        )


def test_protocol_repair_rejects_consumer_without_component_evidence(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    (repo / "other.py").write_text("def consume(value): return value\n")
    original = component()
    original["protocol_contract"] = contract()
    revised = deepcopy(original["protocol_contract"])
    revised["consumers"] = [
        revised["consumers"][0],
        {"file_id": "other.py", "unit_id": "function:consume", "role": "new consumer"},
    ]
    with pytest.raises(ValueError, match="consumers without component evidence"):
        repair_component_with_agent(
            Repairer({
                "status": "repaired", "repair_target": "protocol_contract", "reason": "Fixture",
                "changes": ["consumers: replace lookup"], "protocol_contract": revised,
            }),
            repo,
            original,
            {"repair_target": "protocol_contract", "allowed_protocol_fields": ["consumers"]},
            tmp_path / "missing-consumer-evidence",
        )


def test_review_manifest_repair_can_only_correct_citation_ranges(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value):\n    return value.strip().lower()\n")
    original = component()
    review = {
        "status": "confirmed", "reason": "Reusable normalization.",
        "confirmed_members": deepcopy(original["members"]),
        "evidence": [{"file_id": "module.py", "line_start": 1, "line_end": 9,
                      "claim": "Defines normalization."}],
        "limitations": [],
        "artifact_review": {"status": "faithful", "reason": "Exact behavior."},
        "smoke_test": {"status": "not_run", "reason": "Citation repair only."},
    }
    repaired = deepcopy(review)
    repaired["evidence"][0]["line_end"] = 2
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired", "repair_target": "review_manifest", "reason": "Fixed line range.",
            "changes": ["evidence[0]: line_end 9 -> 2"], "review": repaired,
        }),
        repo, original,
        {"repair_target": "review_manifest", "allowed_review_changes": ["citation_line_ranges"],
         "previous_review": review},
        tmp_path / "repair",
    )
    assert result["review"]["evidence"][0]["line_end"] == 2


def test_review_manifest_repair_can_replace_one_approved_invalid_citation_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    original = component()
    review = {
        "status": "confirmed", "reason": "Reusable normalization.",
        "confirmed_members": deepcopy(original["members"]),
        "evidence": [{"file_id": "component_bundle/common.py", "line_start": 1, "line_end": 1,
                      "claim": "Defines normalization."}],
        "limitations": [],
        "artifact_review": {"status": "faithful", "reason": "Exact behavior."},
        "smoke_test": {"status": "not_run", "reason": "Citation repair only."},
    }
    repaired = deepcopy(review)
    repaired["evidence"][0]["file_id"] = "module.py"
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired", "repair_target": "review_manifest",
            "reason": "Point the unchanged claim at the original source.",
            "changes": ["evidence[0]: replace invalid component path"], "review": repaired,
        }),
        repo,
        original,
        {
            "repair_target": "review_manifest",
            "allowed_review_changes": ["citation_file_paths"],
            "allowed_original_citation_files": ["component_bundle/common.py"],
            "max_citation_file_path_changes": 1,
            "previous_review": review,
        },
        tmp_path / "repair-path",
    )
    assert result["review"]["evidence"][0]["file_id"] == "module.py"


def test_review_manifest_repair_can_add_empty_revised_contract_for_confirmed_protocol(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    original["protocol_contract"] = contract()
    review = {
        "status": "confirmed",
        "reason": "Reusable normalization.",
        "confirmed_members": deepcopy(original["members"]),
        "evidence": deepcopy(original["evidence"]),
        "limitations": [],
        "artifact_review": {"status": "faithful", "reason": "Exact behavior."},
        "smoke_test": {"status": "not_run", "reason": "Shape repair only."},
        "protocol_contract_review": {
            "status": "confirmed",
            "reason": "All fields match source.",
            "confirmed_fields": list(contract()),
            "field_issues": [],
        },
    }
    repaired = deepcopy(review)
    repaired["protocol_contract_review"]["revised_contract"] = {}
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired",
            "repair_target": "review_manifest",
            "reason": "Add the required empty revised contract.",
            "changes": ["protocol review: add revised_contract={}"],
            "review": repaired,
        }),
        repo,
        original,
        {
            "repair_target": "review_manifest",
            "allowed_review_changes": ["protocol_review_empty_revised_contract"],
            "previous_review": review,
        },
        tmp_path / "repair-confirmed-shape",
    )
    assert result["review"]["protocol_contract_review"]["revised_contract"] == {}


def test_review_manifest_repair_can_fix_only_disputed_revised_contract_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    original["protocol_contract"] = contract()
    revised_contract = deepcopy(original["protocol_contract"])
    revised_contract["reuse_interface"] = {
        "mode": "stable_entrypoint",
        "value": "missing_entrypoint",
    }
    review = {
        "status": "confirmed",
        "reason": "Reusable normalization.",
        "confirmed_members": deepcopy(original["members"]),
        "evidence": deepcopy(original["evidence"]),
        "limitations": [],
        "artifact_review": {"status": "faithful", "reason": "Exact behavior."},
        "smoke_test": {"status": "not_run", "reason": "Manifest repair only."},
        "protocol_contract_review": {
            "status": "needs_revision",
            "reason": "Reuse entrypoint is invalid.",
            "confirmed_fields": [field for field in contract() if field != "reuse_interface"],
            "field_issues": [{
                "field": "reuse_interface",
                "status": "inaccurate",
                "issue": "The proposed reuse entrypoint is not declared.",
                "evidence": [{
                    "file_id": "module.py",
                    "line_start": 1,
                    "line_end": 1,
                    "claim": "normalize is the declared implementation entrypoint.",
                }],
            }],
            "revised_contract": revised_contract,
        },
    }
    repaired = deepcopy(review)
    repaired["protocol_contract_review"]["revised_contract"]["reuse_interface"] = {
        "mode": "stable_entrypoint",
        "value": "normalize",
    }
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired",
            "repair_target": "review_manifest",
            "reason": "Use the declared extraction entrypoint.",
            "changes": ["revised reuse_interface: missing_entrypoint -> normalize"],
            "review": repaired,
        }),
        repo,
        original,
        {
            "repair_target": "review_manifest",
            "allowed_review_changes": ["protocol_review_revised_fields"],
            "allowed_protocol_review_fields": ["reuse_interface"],
            "previous_review": review,
        },
        tmp_path / "repair-revised-field",
    )
    assert result["review"]["protocol_contract_review"]["revised_contract"]["reuse_interface"]["value"] == "normalize"


def test_review_manifest_repair_can_merge_duplicate_protocol_issues(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    original["protocol_contract"] = contract()
    revised_contract = deepcopy(original["protocol_contract"])
    revised_contract["extension_trigger"] = "Edit the implementation for a new label syntax."
    first = {
        "field": "extension_trigger",
        "status": "overstated",
        "issue": "No registry exists.",
        "evidence": [{
            "file_id": "module.py", "line_start": 1, "line_end": 1,
            "claim": "The implementation is direct.",
        }],
    }
    second = {
        "field": "extension_trigger",
        "status": "incomplete",
        "issue": "The caller path is omitted.",
        "evidence": [{
            "file_id": "consumer.py", "line_start": 1, "line_end": 1,
            "claim": "The caller invokes the implementation directly.",
        }],
    }
    boundary_issue = {
        "field": "boundary",
        "status": "incomplete",
        "issue": "Storage ownership is omitted.",
        "evidence": [{
            "file_id": "consumer.py", "line_start": 1, "line_end": 1,
            "claim": "The consumer owns storage.",
        }],
    }
    review = {
        "status": "confirmed",
        "reason": "Reusable normalization.",
        "confirmed_members": deepcopy(original["members"]),
        "evidence": deepcopy(original["evidence"]),
        "limitations": [],
        "artifact_review": {"status": "faithful", "reason": "Exact behavior."},
        "smoke_test": {"status": "not_run", "reason": "Manifest repair only."},
        "protocol_contract_review": {
            "status": "needs_revision",
            "reason": "The trigger has two related defects.",
            "confirmed_fields": [
                field for field in contract() if field not in {"extension_trigger", "boundary"}
            ],
            "field_issues": [first, second, boundary_issue],
            "revised_contract": revised_contract,
        },
    }
    review["protocol_contract_review"]["revised_contract"]["boundary"] = (
        "Storage is owned by the consumer."
    )
    repaired = deepcopy(review)
    repaired["protocol_contract_review"]["field_issues"] = [
        {
            "field": "extension_trigger",
            "status": "overstated",
            "issue": "No registry exists.\nThe caller path is omitted.",
            "evidence": [*first["evidence"], *second["evidence"]],
        },
        boundary_issue,
    ]
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired",
            "repair_target": "review_manifest",
            "reason": "Merge duplicate field issues without dropping evidence.",
            "changes": ["protocol review: merge duplicate extension_trigger issues"],
            "review": repaired,
        }),
        repo,
        original,
        {
            "repair_target": "review_manifest",
            "allowed_review_changes": ["protocol_review_merge_duplicate_issues"],
            "previous_review": review,
        },
        tmp_path / "repair-duplicate-issues",
    )
    assert len(result["review"]["protocol_contract_review"]["field_issues"]) == 2


def test_review_manifest_repair_can_remove_only_members_outside_candidate_boundary(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    review = {
        "status": "confirmed",
        "reason": "Reusable normalization.",
        "confirmed_members": [
            *deepcopy(original["members"]),
            {"file_id": "module.py", "unit_id": "function:extra"},
        ],
        "evidence": deepcopy(original["evidence"]),
        "limitations": [],
        "artifact_review": {"status": "faithful", "reason": "Exact behavior."},
        "smoke_test": {"status": "not_run", "reason": "Boundary repair only."},
    }
    repaired = deepcopy(review)
    repaired["confirmed_members"] = deepcopy(original["members"])
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired",
            "repair_target": "review_manifest",
            "reason": "Remove the member outside the frozen component boundary.",
            "changes": ["confirmed_members: remove function:extra"],
            "review": repaired,
        }),
        repo,
        original,
        {
            "repair_target": "review_manifest",
            "allowed_review_changes": ["confirmed_member_boundary"],
            "previous_review": review,
        },
        tmp_path / "repair-member-boundary",
    )
    assert result["review"]["confirmed_members"] == original["members"]


def test_artifact_repair_must_preserve_entrypoint_and_remove_relative_imports(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    original = component("from .helper import clean\n\ndef normalize(value):\n    return clean(value)\n")
    repaired = "from package.helper import clean\n\ndef normalize(value):\n    return clean(value)\n"
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired", "repair_target": "artifact", "reason": "Use absolute import.",
            "changes": ["import: replace package-relative helper import"],
            "library": {"path": "repaired/common.py", "content": repaired},
        }),
        repo, original,
        {"repair_target": "artifact", "max_changed_lines": 4},
        tmp_path / "repair",
    )
    assert result["library"]["content"] == repaired

    broken = repaired.replace("normalize", "renamed")
    with pytest.raises(ValueError, match="removed a declared entrypoint"):
        repair_component_with_agent(
            Repairer({
                "status": "repaired", "repair_target": "artifact", "reason": "Bad rename.",
                "changes": ["rename"], "library": {"path": "repaired/common.py", "content": broken},
            }),
            repo, original,
            {"repair_target": "artifact", "max_changed_lines": 8},
            tmp_path / "broken",
        )


def test_component_evidence_repair_only_appends_required_source_citations(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def normalize(value): return value\n")
    (repo / "consumer.py").write_text("def lookup(value): return value\n")
    original = component()
    original["summary"] = "Normalize labels for lookup."
    original["type"] = "cooperating_units"
    original["evidence"] = [
        {"file_id": "module.py", "line_start": 1, "line_end": 1, "claim": "Defines normalize."}
    ]
    original["protocol_contract"] = contract()
    repaired = [
        *deepcopy(original["evidence"]),
        {"file_id": "consumer.py", "line_start": 1, "line_end": 1, "claim": "Consumes labels."},
    ]
    result = repair_component_with_agent(
        Repairer({
            "status": "repaired",
            "repair_target": "component_evidence",
            "reason": "Add the missing consumer citation.",
            "changes": ["evidence: cite consumer.py"],
            "evidence": repaired,
        }),
        repo,
        original,
        {
            "repair_target": "component_evidence",
            "required_evidence_files": ["consumer.py"],
            "max_evidence_additions": 1,
        },
        tmp_path / "repair-evidence",
    )
    assert result["evidence"] == repaired

    changed = deepcopy(repaired)
    changed[0]["claim"] = "Rewrote existing evidence."
    with pytest.raises(ValueError, match="changed or reordered"):
        repair_component_with_agent(
            Repairer({
                "status": "repaired",
                "repair_target": "component_evidence",
                "reason": "Bad repair.",
                "changes": ["evidence: rewrite"],
                "evidence": changed,
            }),
            repo,
            original,
            {
                "repair_target": "component_evidence",
                "required_evidence_files": ["consumer.py"],
                "max_evidence_additions": 1,
            },
            tmp_path / "broken-evidence",
        )


def test_submission_hydrates_repaired_artifact(tmp_path):
    (tmp_path / "repaired").mkdir()
    (tmp_path / "repaired/common.py").write_text("def normalize(value): return value\n")
    (tmp_path / "manifest.json").write_text(
        '{"status":"repaired","repair_target":"artifact","reason":"fix",'
        '"changes":["import"],"library":{"path":"repaired/common.py"}}'
    )
    result = load_submission(tmp_path, "repair")
    assert result["library"]["content"].startswith("def normalize")
