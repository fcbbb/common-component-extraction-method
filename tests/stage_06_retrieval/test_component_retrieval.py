"""Exercise frozen-library retrieval prompts and file submission checks."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from component_method.retrieval import (
    RetrievalRequest,
    build_component_catalog,
    materialize_selected_bundle,
    render_retrieval_task,
    validate_coverage,
    validate_selection,
)
from component_method.retrieval.service import (
    _has_completion_marker,
    _repository_mask_paths,
)
from component_method.library_publish.agent_bundle import (
    validate_agent_bundle,
)


def component_library(root: Path, count: int = 6) -> Path:
    components = []
    for index in range(1, count + 1):
        bundle_id = f"component-{index:03d}"
        doc = root / "docs" / f"{bundle_id}.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(f"# {bundle_id}\nConcrete capability {index}.\n")
        audit = root / "audit" / f"{bundle_id}.json"
        audit.parent.mkdir(exist_ok=True)
        audit.write_text(json.dumps({
            "entrypoints": [{"name": f"capability_{index}"}],
            "protocol_status": "confirmed",
            "protocol_contract": {
                "capability_family": "dispatcher",
                "semantic_domain": "Optional runtime values",
                "extension_trigger": "A new runtime representation enters the subsystem.",
                "consumers": [{
                    "file_id": "core.py",
                    "unit_id": f"function:consume_{index}",
                    "role": "Consumes the runtime value.",
                }],
                "reuse_interface": {
                    "mode": "reference_pattern",
                    "value": f"capability_{index}",
                },
                "boundary": "Does not implement task-specific behavior.",
            },
        }))
        components.append({
            "bundle_id": bundle_id,
            "readme": f"docs/{bundle_id}.md",
            "audit_file": f"audit/{bundle_id}.json",
        })
    (root / "manifest.json").write_text(json.dumps({
        "repository": "example/project",
        "components": components,
    }))
    (root / "INDEX.md").write_text("# Components\n")
    return root


def selection(root: Path, count: int = 1) -> Path:
    selected = []
    for index in range(1, count + 1):
        bundle_id = f"component-{index:03d}"
        selected.append({
            "bundle_id": bundle_id,
            "delivery_mode": "reference_pattern",
            "task_overlap": "Both concern optional-value type handling.",
            "incremental_contribution": (
                "This adds a runtime dispatch registration protocol absent from the task."
            ),
            "usage": "Adapt the documented registration pattern for the new runtime type.",
            "boundary": "It does not provide the task-specific implementation.",
            "evidence": [{
                "path": f"docs/{bundle_id}.md",
                "line_start": 2,
                "line_end": 2,
                "excerpt": f"Concrete capability {index}.",
            }],
        })
    path = root.parent / "selection.json"
    path.write_text(json.dumps({
        "schema_version": 4,
        "task_id": "task-1",
        "task_baseline": {
            "explicit_information": [
                "The task explicitly requires optional-value handling.",
            ],
            "obvious_scope": "The named type parser and its direct caller.",
        },
        "selected": selected,
    }))
    return path


def coverage_selection(root: Path, *, selected_count: int = 1, shortlist_count: int = 2) -> Path:
    path = selection(root, count=selected_count)
    value = json.loads(path.read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    bundle_ids = [component["bundle_id"] for component in manifest["components"]]
    shortlisted = bundle_ids[:shortlist_count]
    value.update({
        "schema_version": 5,
        "change_model": {
            "changed_entities": ["optional runtime value"],
            "introduced_or_changed_variants": ["a new optional runtime representation"],
            "change_kinds": ["representation", "dispatch"],
            "propagation_risks": [
                "Consumers may dispatch differently for the new runtime representation."
            ],
        },
        "component_assessments": [
            {
                "bundle_id": bundle_id,
                "relation": "protocol" if bundle_id in shortlisted else "none",
                "decision": "shortlist" if bundle_id in shortlisted else "reject",
                "reason": (
                    "The catalog exposes a dispatch boundary worth detailed inspection."
                    if bundle_id in shortlisted
                    else "The catalog contains no grounded relation to the described change."
                ),
            }
            for bundle_id in bundle_ids
        ],
        "shortlisted_bundle_ids": shortlisted,
    })
    path.write_text(json.dumps(value))
    return path


def staged_selection(root: Path, *, selected_count: int = 1, covered_count: int = 2) -> tuple[Path, Path]:
    path = coverage_selection(
        root,
        selected_count=selected_count,
        shortlist_count=covered_count,
    )
    value = json.loads(path.read_text())
    changed_entities = value["change_model"]["changed_entities"]
    manifest = json.loads((root / "manifest.json").read_text())
    bundle_ids = [component["bundle_id"] for component in manifest["components"]]
    covered = set(bundle_ids[:covered_count])
    coverage_path = root.parent / "coverage.json"
    coverage_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": value["task_id"],
        "change_model": value["change_model"],
        "component_coverage": [
            {
                "bundle_id": bundle_id,
                "relation": "protocol" if bundle_id in covered else "none",
                "changed_entities": changed_entities if bundle_id in covered else [],
                "catalog_signals": (
                    ["semantic_domain", "consumers"] if bundle_id in covered else []
                ),
                "path": (
                    "The changed runtime value crosses the documented consumer boundary."
                    if bundle_id in covered
                    else "No changed semantic entity crosses this documented component boundary."
                ),
            }
            for bundle_id in bundle_ids
        ],
    }))
    value["schema_version"] = 6
    value["coverage_sha256"] = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(value))
    return path, coverage_path


def reviewed_selection(
    root: Path, *, selected_count: int = 1, covered_count: int = 2
) -> tuple[Path, Path]:
    path, coverage_path = staged_selection(
        root,
        selected_count=selected_count,
        covered_count=covered_count,
    )
    value = json.loads(path.read_text())
    value["schema_version"] = 7
    value["shortlist_reviews"] = []
    for index, bundle_id in enumerate(value["shortlisted_bundle_ids"], start=1):
        value["shortlist_reviews"].append({
            "bundle_id": bundle_id,
            "decision": "select" if index <= selected_count else "omit",
            "marginal_value": (
                "Detailed source proves a distinct runtime dispatch obligation."
                if index <= selected_count
                else "Detailed source duplicates behavior already covered by a stronger component."
            ),
            "boundary": "The component does not implement task-specific behavior.",
            "evidence": [{
                "path": f"docs/{bundle_id}.md",
                "line_start": 2,
                "line_end": 2,
                "excerpt": f"Concrete capability {index}.",
            }],
        })
    path.write_text(json.dumps(value))
    return path, coverage_path


def adjudicated_selection(
    root: Path, *, selected_count: int = 1, covered_count: int = 2
) -> tuple[Path, Path]:
    path, coverage_path = reviewed_selection(
        root,
        selected_count=selected_count,
        covered_count=covered_count,
    )
    value = json.loads(path.read_text())
    value["schema_version"] = 8
    selected_ids = {
        review["bundle_id"]
        for review in value["shortlist_reviews"]
        if review["decision"] == "select"
    }
    selected_target = next(iter(selected_ids))
    for review in value["shortlist_reviews"]:
        selected = review["bundle_id"] in selected_ids
        review["coverage_verdict"] = "confirmed" if selected else "duplicate"
        review["duplicate_of"] = None if selected else selected_target
    path.write_text(json.dumps(value))
    return path, coverage_path


def closure_selection(root: Path) -> tuple[Path, Path]:
    path, coverage_path = adjudicated_selection(root)
    value = json.loads(path.read_text())
    value["schema_version"] = 9
    value["propagation_checks"] = [{
        "carrier": "optional runtime representation independent of the named task method",
        "changed_variants": value["change_model"]["introduced_or_changed_variants"],
        "bundle_ids": ["component-001"],
        "symbols": ["capability_1", "sibling_capability"],
        "argument_positions": ["capability_1.value", "sibling_capability.candidate"],
        "invariant": "The optional representation must follow the same dispatch rule everywhere.",
        "evidence": [{
            "path": "docs/component-001.md",
            "line_start": 2,
            "line_end": 2,
            "excerpt": "Concrete capability 1.",
        }],
    }]
    path.write_text(json.dumps(value))
    return path, coverage_path


def test_retrieval_selection_is_grounded_in_bundle_files(tmp_path):
    library = component_library(tmp_path / "library")
    result = validate_selection(library, selection(library), expected_task_id="task-1")
    assert result["selected_bundle_ids"] == ["component-001"]
    assert result["method"] == "marginal_value_retrieval_over_frozen_component_library"


def test_retrieval_accepts_empty_selection_and_rejects_more_than_five(tmp_path):
    library = component_library(tmp_path / "library")
    result = validate_selection(library, selection(library, count=0), expected_task_id="task-1")
    assert result["selected_bundle_ids"] == []
    with pytest.raises(ValueError, match="between 0 and 5"):
        validate_selection(library, selection(library, count=6), expected_task_id="task-1")


def test_retrieval_rejects_wrong_evidence_or_delivery_mode(tmp_path):
    library = component_library(tmp_path / "library")
    path = selection(library)
    value = json.loads(path.read_text())
    value["selected"][0]["evidence"][0]["excerpt"] = "invented"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="not exact"):
        validate_selection(library, path, expected_task_id="task-1")

    path = selection(library)
    value = json.loads(path.read_text())
    value["selected"][0]["delivery_mode"] = "inspection"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="delivery_mode"):
        validate_selection(library, path, expected_task_id="task-1")


def test_retrieval_prompt_passes_path_not_inline_catalog(tmp_path):
    library = component_library(tmp_path / "library")
    request = RetrievalRequest(
        task_id="task-1",
        problem_statement="Handle optional values.",
        interface="method(value: T | None)",
        component_library=library,
        output_dir=tmp_path / "output",
        image="fixture",
    )
    prompt = render_retrieval_task(request)
    assert "/component-library" in prompt
    assert "Handle optional values." in prompt
    assert "Concrete capability 1" not in prompt
    assert '"schema_version": 9' in prompt
    assert "/component-output/coverage.json" in prompt
    assert "/retrieval-tools/component_catalog.json" in prompt
    assert "component-001" not in prompt
    assert "component-002" not in prompt
    assert "<catalog-bundle-id-a>" in prompt


def test_retrieval_mask_paths_follow_library_repository():
    assert _repository_mask_paths(
        {"repository": "example/alpha"},
        ("/testbed", "/root/my_repo"),
    ) == ("/testbed", "/root/my_repo", "/alpha")
    assert _repository_mask_paths(
        {"repository": "example/beta.git"},
        ("/testbed", "/root/my_repo"),
    ) == ("/testbed", "/root/my_repo", "/beta")
    with pytest.raises(ValueError, match="must declare repository"):
        _repository_mask_paths({}, ("/testbed", "/root/my_repo"))


def test_retrieval_system_prompt_prioritizes_incremental_value():
    prompt = " ".join((
        Path(__file__).parents[2]
        / "src/component_method/retrieval/prompts/retrieve_system.txt"
    ).read_text().split())
    assert "not to cover the task" in prompt
    assert "beyond what the task statement and interface already provide" in prompt
    assert "task baseline" in prompt
    assert "direct_reuse" in prompt
    assert "reference_pattern" in prompt
    assert "perform a complete coverage pass over every catalog entry" in prompt
    assert "Use one Agent and two mechanically separated phases" in prompt
    assert "before any relevance or marginal-value decision" in prompt
    assert "COVERAGE_VALID_CONTINUE_SELECTION" in prompt
    assert "does not need to parse, validate, or implement" in prompt
    assert "shortlist_reviews" in prompt
    assert "may not omit a component without opening its detailed files" in prompt
    assert "Absence from the task traceback" in prompt
    assert "check direct coverage before consumer protocols" in prompt
    assert "whether code in that component ultimately needs a patch" in prompt
    assert "change model" in prompt
    assert "Inspect detailed README, audit, and source files only for" in prompt
    assert "marginal value over the task baseline" in prompt
    assert "only restates the task" in prompt
    assert "Prefer one strong component" in prompt
    assert "zero to five" in prompt
    assert "There is no minimum quota" in prompt
    assert "not a question for the Task Agent" in prompt


def test_retrieval_completion_marker_can_follow_coverage_output():
    assert _has_completion_marker({
        "output": (
            "COVERAGE_VALID_CONTINUE_SELECTION\n"
            "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n"
        )
    })
    assert not _has_completion_marker({"output": "COVERAGE_VALID_CONTINUE_SELECTION\n"})


def test_component_catalog_covers_manifest_with_protocol_metadata(tmp_path):
    library = component_library(tmp_path / "library", count=2)
    audit = library / "audit/component-001.json"
    audit.write_text(json.dumps({
        "component_id": "dispatch-rule",
        "name": "Dispatch rule",
        "capability": "Routes values according to runtime type.",
        "entrypoints": [{"name": "register"}],
        "protocol_status": "confirmed",
        "protocol_contract": {
            "capability_family": "dispatcher",
            "semantic_domain": "Runtime values",
            "extension_trigger": "A new runtime type enters the subsystem.",
            "consumers": [{
                "file_id": "core.py",
                "unit_id": "function:consume",
                "role": "Consumes registered values.",
            }],
            "reuse_interface": {"mode": "reference_pattern", "value": "register"},
            "boundary": "Does not implement the new value type.",
        },
    }))
    catalog = build_component_catalog(library)
    assert catalog["component_count"] == 2
    assert [item["bundle_id"] for item in catalog["components"]] == [
        "component-001",
        "component-002",
    ]
    first = catalog["components"][0]
    assert first["capability_family"] == "dispatcher"
    assert first["consumers"][0]["location"] == "core.py:function:consume"
    assert first["entrypoints"] == ["register"]


def test_schema_five_requires_complete_catalog_assessment(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    valid = coverage_selection(library)
    result = validate_selection(library, valid, expected_task_id="task-1")
    assert result["schema_version"] == 5
    assert result["shortlisted_bundle_ids"] == ["component-001", "component-002"]
    assert len(result["component_assessments"]) == 3

    value = json.loads(valid.read_text())
    value["component_assessments"].pop()
    valid.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="cover every manifest component"):
        validate_selection(library, valid, expected_task_id="task-1")


def test_schema_five_requires_shortlist_consistency_and_selection_membership(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    path = coverage_selection(library, selected_count=1, shortlist_count=2)
    value = json.loads(path.read_text())
    value["shortlisted_bundle_ids"] = ["component-001"]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="exactly match"):
        validate_selection(library, path, expected_task_id="task-1")

    path = coverage_selection(library, selected_count=2, shortlist_count=1)
    with pytest.raises(ValueError, match="must first appear"):
        validate_selection(library, path, expected_task_id="task-1")


def test_schema_six_requires_valid_staged_coverage(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = staged_selection(library)
    coverage = validate_coverage(library, coverage_path, expected_task_id="task-1")
    assert coverage["covered_bundle_ids"] == ["component-001", "component-002"]

    result = validate_selection(
        library,
        selection_path,
        expected_task_id="task-1",
        coverage_path=coverage_path,
    )
    assert result["schema_version"] == 6
    assert result["method"] == "staged_protocol_coverage_then_marginal_value_retrieval"
    assert result["protocol_coverage"]["covered_bundle_ids"] == [
        "component-001",
        "component-002",
    ]


def test_schema_six_binds_selection_to_validated_coverage(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = staged_selection(library)
    value = json.loads(selection_path.read_text())
    value["component_assessments"][0]["relation"] = "none"
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="relation must match coverage"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_schema_seven_requires_evidenced_review_for_every_shortlist_item(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = reviewed_selection(library)
    result = validate_selection(
        library,
        selection_path,
        expected_task_id="task-1",
        coverage_path=coverage_path,
    )
    assert result["schema_version"] == 7
    assert result["method"] == (
        "staged_protocol_coverage_then_evidenced_marginal_value_retrieval"
    )
    assert [item["bundle_id"] for item in result["shortlist_reviews"]] == [
        "component-001",
        "component-002",
    ]

    value = json.loads(selection_path.read_text())
    value["shortlist_reviews"].pop()
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="cover every shortlisted component"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_schema_seven_binds_selected_ids_to_review_decisions(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = reviewed_selection(library)
    value = json.loads(selection_path.read_text())
    value["shortlist_reviews"][0]["decision"] = "omit"
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="selected IDs must exactly match"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_schema_eight_requires_confirmed_coverage_to_be_selected(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = adjudicated_selection(library)
    result = validate_selection(
        library,
        selection_path,
        expected_task_id="task-1",
        coverage_path=coverage_path,
    )
    assert result["schema_version"] == 8
    assert result["method"] == (
        "staged_protocol_coverage_then_adjudicated_marginal_value_retrieval"
    )

    value = json.loads(selection_path.read_text())
    value["shortlist_reviews"][0]["decision"] = "omit"
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="confirmed coverage must be selected"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_schema_nine_requires_propagation_closure(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = closure_selection(library)
    result = validate_selection(
        library,
        selection_path,
        expected_task_id="task-1",
        coverage_path=coverage_path,
    )
    assert result["schema_version"] == 9
    assert result["propagation_checks"][0]["symbols"] == [
        "capability_1",
        "sibling_capability",
    ]

    value = json.loads(selection_path.read_text())
    value["propagation_checks"][0]["changed_variants"] = []
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="changed_variants"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_schema_eight_duplicate_must_name_a_selected_component(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = adjudicated_selection(library)
    value = json.loads(selection_path.read_text())
    value["shortlist_reviews"][1]["duplicate_of"] = "component-003"
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="another shortlisted duplicate_of"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_schema_eight_cannot_refute_confirmed_catalog_protocol(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = adjudicated_selection(library)
    value = json.loads(selection_path.read_text())
    value["shortlist_reviews"][0].update({
        "decision": "omit",
        "coverage_verdict": "refuted",
        "duplicate_of": None,
    })
    selection_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="confirmed catalog coverage cannot be refuted"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_result_artifact_finds_submission_coverage(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    selection_path, coverage_path = adjudicated_selection(library)
    attempt = tmp_path / "attempt"
    submission = attempt / "submission"
    submission.mkdir(parents=True)
    result_path = attempt / "result.json"
    result_path.write_bytes(selection_path.read_bytes())
    (submission / "coverage.json").write_bytes(coverage_path.read_bytes())

    result = validate_selection(library, result_path, expected_task_id="task-1")
    assert result["selected_bundle_ids"] == ["component-001"]

    selection_path, coverage_path = staged_selection(library)
    coverage_value = json.loads(coverage_path.read_text())
    coverage_value["component_coverage"][0]["path"] += " Updated after validation."
    coverage_path.write_text(json.dumps(coverage_value))
    with pytest.raises(ValueError, match="coverage_sha256"):
        validate_selection(
            library,
            selection_path,
            expected_task_id="task-1",
            coverage_path=coverage_path,
        )


def test_coverage_requires_complete_catalog_and_grounded_signals(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    _, coverage_path = staged_selection(library)
    value = json.loads(coverage_path.read_text())
    value["component_coverage"].pop()
    coverage_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="cover every manifest component"):
        validate_coverage(library, coverage_path, expected_task_id="task-1")

    _, coverage_path = staged_selection(library)
    value = json.loads(coverage_path.read_text())
    value["component_coverage"][0]["catalog_signals"] = ["missing_field"]
    coverage_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="unknown catalog signals"):
        validate_coverage(library, coverage_path, expected_task_id="task-1")

    _, coverage_path = staged_selection(library)
    value = json.loads(coverage_path.read_text())
    value["change_model"]["introduced_or_changed_variants"] = []
    coverage_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="representation changes require"):
        validate_coverage(library, coverage_path, expected_task_id="task-1")


def test_coverage_schema_two_binds_direct_assessment_to_relation(tmp_path):
    library = component_library(tmp_path / "library", count=3)
    _, coverage_path = staged_selection(library)
    value = json.loads(coverage_path.read_text())
    value["schema_version"] = 2
    for entry in value["component_coverage"]:
        is_direct = entry["bundle_id"] == "component-001"
        if is_direct:
            entry["relation"] = "direct"
        entry["direct_assessment"] = {
            "verdict": "match" if is_direct else "no_match",
            "matched_entities": (
                value["change_model"]["introduced_or_changed_variants"]
                if is_direct
                else []
            ),
            "catalog_signals": ["semantic_domain"] if is_direct else [],
            "reason": (
                "The declared semantic domain directly includes the introduced representation."
                if is_direct
                else "The declared reusable behavior does not include the changed representation."
            ),
            "probe": (
                "capability_1 receives the introduced optional runtime representation."
                if is_direct
                else "capability_2 cannot receive the introduced optional runtime representation."
            ),
            "entrypoint": f"capability_{int(entry['bundle_id'].split('-')[1])}",
            "can_invoke_with_variant": is_direct,
        }
    coverage_path.write_text(json.dumps(value))
    result = validate_coverage(library, coverage_path, expected_task_id="task-1")
    assert result["schema_version"] == 2

    value["component_coverage"][0]["relation"] = "none"
    value["component_coverage"][0]["changed_entities"] = []
    value["component_coverage"][0]["catalog_signals"] = []
    coverage_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="direct match requires relation direct"):
        validate_coverage(library, coverage_path, expected_task_id="task-1")

    value["component_coverage"][0]["direct_assessment"] = {
        "verdict": "no_match",
        "matched_entities": [],
        "catalog_signals": [],
        "reason": "The declared reusable behavior does not include the changed representation.",
        "entrypoint": "capability_1",
        "probe": "capability_1 cannot receive the introduced optional runtime representation.",
        "can_invoke_with_variant": False,
    }
    value["component_coverage"][0]["relation"] = "direct"
    value["component_coverage"][0]["changed_entities"] = value["change_model"][
        "changed_entities"
    ]
    value["component_coverage"][0]["catalog_signals"] = ["semantic_domain"]
    coverage_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="relation direct requires a direct match"):
        validate_coverage(library, coverage_path, expected_task_id="task-1")

def test_retrieval_rejects_invalid_task_baseline(tmp_path):
    library = component_library(tmp_path / "library")
    path = selection(library)
    value = json.loads(path.read_text())
    value["task_baseline"]["explicit_information"] = []
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="explicit_information"):
        validate_selection(library, path, expected_task_id="task-1")



def test_retrieval_rejects_selected_components_with_identical_source(tmp_path):
    library = component_library(tmp_path / "library")
    manifest_path = library / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for index, component in enumerate(manifest["components"], start=1):
        source = library / "sources" / f"component-{index:03d}.py"
        source.parent.mkdir(exist_ok=True)
        source.write_text("VALUE = 1\n" if index < 3 else f"VALUE = {index}\n")
        component["library"] = source.relative_to(library).as_posix()
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="duplicates source content"):
        validate_selection(library, selection(library, count=2), expected_task_id="task-1")


def test_retrieval_rejects_selected_components_with_same_entrypoint_family(tmp_path):
    library = component_library(tmp_path / "library")
    second_audit = library / "audit/component-002.json"
    second_audit.write_text(json.dumps({
        "entrypoints": [{"name": "capability_1"}],
    }))

    with pytest.raises(ValueError, match="duplicates entrypoint family"):
        validate_selection(library, selection(library, count=2), expected_task_id="task-1")


def test_materialize_selected_bundle_preserves_incremental_handoff(tmp_path):
    library = tmp_path / "library"
    records = []
    for index in range(1, 3):
        bundle_id = f"component-{index:03d}"
        component_dir = library / "components" / bundle_id
        component_dir.mkdir(parents=True)
        (component_dir / "component.py").write_text(f"VALUE = {index}\n")
        (component_dir / "README.md").write_text(f"# Capability {index}\n")
        audit = library / "audit" / f"{bundle_id}.json"
        audit.parent.mkdir(exist_ok=True)
        audit.write_text(json.dumps({
            "name": f"Capability {index}",
            "capability": f"Concrete capability {index}.",
            "entrypoints": [{"name": f"selected_value_{index}"}],
        }))
        records.append({
            "bundle_id": bundle_id,
            "library": f"components/{bundle_id}/component.py",
            "readme": f"components/{bundle_id}/README.md",
            "audit_file": f"audit/{bundle_id}.json",
        })
    (library / "README.md").write_text("# Bundle\n")
    (library / "INDEX.md").write_text("# Component index\n")
    (library / "manifest.json").write_text(json.dumps({
        "schema_version": 7,
        "repository": "owner/repo",
        "source_commit": "a" * 40,
        "component_count": 2,
        "components_file": "INDEX.md",
        "libraries": [record["library"] for record in records],
        "components": records,
    }))
    selected = selection(library, count=1)
    value = json.loads(selected.read_text())
    value.update({
        "schema_version": 5,
        "change_model": {
            "changed_entities": ["optional runtime value"],
            "introduced_or_changed_variants": ["a new optional runtime representation"],
            "change_kinds": ["representation", "dispatch"],
            "propagation_risks": [
                "Sibling dispatch operations may need the same representation handling."
            ],
        },
        "component_assessments": [
            {
                "bundle_id": "component-001",
                "relation": "direct",
                "decision": "shortlist",
                "reason": "The component directly handles the changed runtime representation.",
            },
            {
                "bundle_id": "component-002",
                "relation": "none",
                "decision": "reject",
                "reason": "The component has no grounded relation to the changed representation.",
            },
        ],
        "shortlisted_bundle_ids": ["component-001"],
    })
    value["selected"][0]["evidence"][0] = {
        "path": "components/component-001/README.md",
        "line_start": 1,
        "line_end": 1,
        "excerpt": "# Capability 1",
    }
    selected.write_text(json.dumps(value))

    destination = materialize_selected_bundle(
        library,
        selected,
        tmp_path / "selected",
        expected_task_id="task-1",
    )
    manifest = validate_agent_bundle(destination, "owner/repo", "a" * 40)
    assert manifest["selected_bundle_ids"] == ["component-001"]
    assert manifest["component_count"] == 1
    assert not (destination / "components/component-002").exists()
    index = (destination / "INDEX.md").read_text()
    assert "Delivery mode: `reference_pattern`" in index
    assert "Incremental contribution:" in index
    assert "How to use:" in index
    assert "Change propagation" in index
    assert "Sibling dispatch operations" in index
    assert "role-independent carrier" in index
    assert "every applicable argument position" in index
    assert "remove scratch or probe files" in index
    assert "Recognition level" not in index
    persisted = json.loads((destination / "selection.json").read_text())
    assert persisted["task_baseline"] == value["task_baseline"]
    assert persisted["selected"][0]["incremental_contribution"] == (
        value["selected"][0]["incremental_contribution"]
    )
    selection_doc = (destination / "SELECTION.md").read_text()
    assert "Task baseline" in selection_doc
    assert "Frozen-library evidence" in selection_doc
    assert destination.stat().st_mode & 0o777 == 0o755
    assert manifest["components"][0]["import_module"] == "component_api.component_001"
    readme = (destination / "components/component-001/README.md").read_text()
    assert "Task retrieval note" in readme
    assert "Incremental contribution" in readme
    imported = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from component_api.component_001 import VALUE; print(VALUE)",
        ],
        cwd=destination,
        text=True,
    )
    assert imported.strip() == "1"
