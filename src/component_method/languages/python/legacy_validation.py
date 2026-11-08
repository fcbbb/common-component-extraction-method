"""One validation pipeline for all common-component discovery strategies."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Any

from component_method.component_build.contracts import RepositoryContext, VALIDATION_RESULT_SCHEMA
from component_method.component_build.experiment import resolve_prompt
from component_method.component_build.validation.runtime import validate_callable_artifact
from component_method.component_build.workspace import COMPONENT_DIRECTORY


PROMPT_DIR = Path(__file__).resolve().parents[2] / "component_build/validation/prompts"
PROTOCOL_CONTRACT_FIELDS = (
    "capability_family",
    "semantic_domain",
    "extension_trigger",
    "covered_variants",
    "downstream_guarantee",
    "consumers",
    "reuse_interface",
    "boundary",
)
PROTOCOL_CONTRACT_ISSUE_STATUSES = {
    "overstated",
    "unsupported",
    "incomplete",
    "inaccurate",
}
PROTOCOL_CONTRACT_ISSUE_SEVERITIES = {"blocking", "warning"}
PROTOCOL_CONTRACT_REVIEW_STATUSES = {
    "confirmed",
    "confirmed_with_warnings",
    "needs_revision",
    "rejected",
}


def _review_brief(candidate_payload: dict[str, Any]) -> dict[str, Any]:
    """Keep review input focused; the reviewer can inspect source in /testbed."""
    candidate = candidate_payload.get("candidate")
    if not isinstance(candidate, dict):
        candidate = candidate_payload

    candidate_fields = (
        "candidate_id",
        "component_id",
        "name",
        "summary",
        "capability",
        "type",
        "confidence",
        "members",
        "relationships",
        "invariants",
        "variation_points",
        "dependencies",
        "entrypoints",
        "limitations",
        "guidance",
        "applicability",
        "integration_steps",
        "protocol_contract",
    )
    brief_candidate = {
        key: candidate[key]
        for key in candidate_fields
        if key in candidate
    }

    evidence = candidate.get("evidence")
    if isinstance(evidence, list):
        brief_candidate["evidence"] = [
            {
                key: item[key]
                for key in ("file_id", "line_start", "line_end", "claim")
                if key in item
            }
            for item in evidence
            if isinstance(item, dict)
        ]

    usage_examples = candidate_payload.get("usage_examples")
    brief_examples = []
    if isinstance(usage_examples, list):
        for item in usage_examples:
            if not isinstance(item, dict):
                continue
            brief_examples.append({
                key: item[key]
                for key in (
                    "file_id",
                    "unit_id",
                    "call_line",
                    "callee_file",
                    "callee_symbol",
                )
                if key in item
            })

    proposed = candidate_payload.get("proposed_component")
    if not isinstance(proposed, dict):
        proposed = candidate.get("component_draft") or candidate.get("agent_extraction") or candidate
    if not isinstance(proposed, dict):
        proposed = {}
    library = proposed.get("library", {})

    return {
        "candidate": brief_candidate,
        "usage_examples": brief_examples,
        "proposed_component": {
            key: proposed[key]
            for key in (
                "members",
                "entrypoints",
                "dependencies",
                "limitations",
                "protocol_contract",
            )
            if key in proposed
        },
        "component_code": library.get("content", "") if isinstance(library, dict) else "",
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def review_component(
    agent_runner: Any,
    candidate_payload: dict[str, Any],
    output_dir: Path,
    *,
    repo_root: Path,
    experiment_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run an independent read-only repository review agent."""
    return review_component_with_agent(
        agent_runner,
        repo_root,
        candidate_payload,
        output_dir,
        experiment_dir=experiment_dir,
    )


def _review_task_prompt(
    candidate_payload: dict[str, Any], experiment_dir: Path | str | None = None,
) -> str:
    """Assemble one value/fidelity review and grounded smoke-plan task."""
    brief = _review_brief(candidate_payload)
    brief.pop("component_code")
    brief["component_file"] = COMPONENT_DIRECTORY + "/common.py"
    schema = {
        "status": "confirmed|rejected|uncertain",
        "reason": "reusable-value decision",
        "confirmed_members": [{"file_id": "relative/path.py", "unit_id": "function:name"}],
        "evidence": [{"file_id": "relative/path.py", "line_start": 1, "line_end": 2, "claim": ""}],
        "limitations": [],
        "validation_dependencies": {"complete": True, "files": ["relative/path.py"], "search_scopes": []},
        "entrypoint_capabilities": [{
            "entrypoint": "name", "method": "",
            "availability": "implemented|missing|unverified", "contract": "input/output and boundary behavior",
            "example": "minimal source-grounded call", "scope": "supported inputs and adaptation conditions",
            "dependencies": [], "reason": "", "case_ids": ["case-1"],
        }],
        "artifact_review": {"status": "faithful|invalid|uncertain|not_checked", "reason": ""},
        "smoke_test": {
            "status": "ready|no_cases|not_run", "reason": "",
            "cases": [{"case_id": "case-1", "entrypoint": "name", "test_file": "cases/case-1.py",
                       "sources": [{"file_id": "relative/path.py", "line_start": 1, "line_end": 2,
                                    "role": "interface_contract"}]}],
        },
    }
    protocol_contract = brief["proposed_component"].get("protocol_contract")
    if not isinstance(protocol_contract, dict):
        protocol_contract = brief["candidate"].get("protocol_contract")
    protocol_instructions = ""
    if isinstance(protocol_contract, dict):
        review_fields, _ = _protocol_review_scope(candidate_payload)
        locked_fields = [
            field for field in PROTOCOL_CONTRACT_FIELDS if field not in review_fields
        ]
        schema["protocol_contract_review"] = {
            "schema_version": 2,
            "status": "confirmed|confirmed_with_warnings|needs_revision|rejected",
            "reason": "overall source-grounded protocol-contract decision",
            "reviewed_fields": list(review_fields),
            "confirmed_fields": list(review_fields),
            "field_issues": [{
                "field": "extension_trigger",
                "status": "overstated|unsupported|incomplete|inaccurate",
                "severity": "blocking|warning",
                "issue": "what the source does not support or what is missing",
                "evidence": [{
                    "file_id": "relative/path.py",
                    "line_start": 1,
                    "line_end": 2,
                    "claim": "source fact supporting this issue",
                }],
            }],
            "field_revisions": {},
        }
        scope_instructions = (
            "Review all eight protocol fields."
            if not locked_fields
            else (
                "This is a scoped verification after a repair. Review only these changed fields: "
                + ", ".join(review_fields)
                + ". Do not reopen these previously decided fields: "
                + ", ".join(locked_fields)
                + ". The controller will merge this result with the previous review."
            )
        )
        protocol_instructions = (
            "\n\nIndependently review the requested protocol_contract fields against repository "
            "source, without using benchmark tasks or anticipated patches. "
            + scope_instructions
            + " Account for every reviewed field name in either confirmed_fields or field_issues, "
            "but not both. A field issue is blocking only when leaving it unchanged could make a task "
            "agent call a nonexistent interface, miss a required integration change, rely on a false "
            "downstream guarantee, or cross the component boundary incorrectly. Naming or taxonomy "
            "imprecision, omitted secondary consumers, non-exhaustive variants, and conservative extra "
            "checks are warnings unless they create one of those concrete reuse failures. In particular, "
            "an incomplete field is normally a warning unless the omission can hide required work. "
            "Use confirmed when there are no issues, confirmed_with_warnings when every issue is a "
            "warning, needs_revision when at least one issue is blocking, and rejected only when the "
            "protocol is fundamentally unsupported. Each issue needs repository source citations. "
            "For needs_revision, return field_revisions for exactly the blocking fields; do not rewrite "
            "the complete contract and do not propose revisions for warnings. Distinguish a trigger that "
            "requires checking an existing protocol from one that always requires code changes, and "
            "inspect fallback or alternative extension paths before making that claim. Keep component "
            "value and artifact-fidelity decisions separate from this metadata decision."
        )
    return (
        resolve_prompt(experiment_dir, "validation/review_system.txt").strip()
        + "\n\nSmoke-test preparation in this same review:\n"
        + resolve_prompt(experiment_dir, "validation/validate_component_system.txt").strip()
        + "\n\nThe workspace is mounted read-only at /testbed. Inspect the "
          "proposed members and extracted code; investigate callers, comparable implementations, "
          "interface contracts, and extension paths as relevant. Verify claims against source, "
          "using tests and documentation to establish intended behavior and usage. Keep the repository read-only "
          "without executing tests. Cite repository-relative paths and exact line ranges. "
          "confirmed_members must stay within the proposed member list.\n\n"
          "The extracted artifact is mounted at " + COMPONENT_DIRECTORY + "/common.py. "
          "Read this file alongside the original repository. Repository imports and installed "
          "runtime dependencies are allowed; full independence is not required.\n"
          "Review evidence may cite repository-relative source files or "
          + f"{Path(COMPONENT_DIRECTORY).name}/common.py "
          "when comparing the extracted artifact. Smoke-test sources must cite original "
          "repository files, not the extracted artifact.\n"
          "Allowed entrypoints are exactly the proposed_component.entrypoints names below. "
          "Do not add helpers or other source symbols as entrypoints. Each case.entrypoint must "
          "equal the entrypoint of every capability that links to that case.\n"
          "For machine coverage, method is an empty string for a function or class constructor, "
          "or one method name for a class operation. Keep signatures and illustrative calls in example. "
          "The program derives the display path.\n\n"
          "First decide reusable value. For confirmed value, assess artifact fidelity. "
          "For confirmed value and a faithful artifact, prepare a grounded smoke test. "
          "Otherwise set smoke_test.status to not_run. Record these decisions separately; "
          "the program executes the test later.\n\nCandidate and supplied source evidence:\n"
        + json.dumps(brief, ensure_ascii=False, indent=2)
        + protocol_instructions
        + "\n\nCase IDs must use only ASCII letters, digits, underscores and hyphens."
        + "\nWrite each case as a .py file defining run(common) inside /component-output; "
          "test_file is its relative path. Write manifest.json matching this combined schema:\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )


def review_component_with_agent(
    agent_runner: Any,
    repo_root: Path,
    candidate_payload: dict[str, Any],
    output_dir: Path,
    *,
    experiment_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Independently review value and fidelity, and prepare smoke in one call."""
    from component_method.component_build.validation.artifact_service import extraction_record, review_artifact_with_agent

    proposed = candidate_payload.get("proposed_component", candidate_payload.get("candidate", candidate_payload))
    if "artifact" in extraction_record(proposed):
        return review_artifact_with_agent(agent_runner, repo_root, proposed, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    brief = _review_brief(candidate_payload)
    protocol_contract = brief["proposed_component"].get("protocol_contract")
    if not isinstance(protocol_contract, dict):
        protocol_contract = brief["candidate"].get("protocol_contract")
    entrypoints = brief["proposed_component"].get("entrypoints")
    if not isinstance(entrypoints, list):
        entrypoints = brief["candidate"].get("entrypoints", [])
    review_fields: tuple[str, ...] | None = None
    previous_protocol_review: dict[str, Any] | None = None
    if isinstance(protocol_contract, dict):
        _validate_protocol_contract_shape(
            protocol_contract,
            repo_root,
            entrypoints,
            label="protocol_contract",
        )
        review_fields, previous_protocol_review = _protocol_review_scope(candidate_payload)
        if previous_protocol_review is not None:
            _validate_protocol_contract_review(
                {"protocol_contract_review": previous_protocol_review},
                protocol_contract,
                repo_root,
                entrypoints,
                artifact_content=brief["component_code"],
            )

    task = _review_task_prompt(candidate_payload, experiment_dir)
    component_workspace = output_dir / "component_workspace"
    component_workspace.mkdir(exist_ok=True)
    (component_workspace / "common.py").write_text(brief["component_code"], encoding="utf-8")
    _write_json(component_workspace / "component.json", brief["proposed_component"])
    result = agent_runner.run_workspace_agent(
        workspace_root=repo_root,
        task=task,
        output_dir=output_dir,
        task_label="component-review-and-smoke",
        agent_role="review",
        component_workspace=component_workspace,
    )
    if result.get("status") not in {"confirmed", "rejected", "uncertain"}:
        raise ValueError("component review returned an invalid status")
    if not isinstance(result.get("reason"), str) or not result["reason"].strip():
        raise ValueError("component review must include a reason")
    for field in ("confirmed_members", "evidence", "limitations"):
        if not isinstance(result.get(field), list):
            raise ValueError(f"component review field {field} must be a list")
    if isinstance(protocol_contract, dict):
        _validate_protocol_contract_review(
            result,
            protocol_contract,
            repo_root,
            entrypoints,
            artifact_content=brief["component_code"],
            review_fields=review_fields,
            require_schema_version=2,
        )
        if previous_protocol_review is not None:
            result["protocol_contract_review"] = merge_protocol_contract_reviews(
                previous_protocol_review,
                result["protocol_contract_review"],
            )
            _validate_protocol_contract_review(
                result,
                protocol_contract,
                repo_root,
                entrypoints,
                artifact_content=brief["component_code"],
                require_schema_version=2,
            )
    # Shell traces add conservative dependencies beyond self-reported citations.
    from component_method.component_build.cache.review import merge_review_dependencies, observed_dependencies
    observed = observed_dependencies(output_dir / "trajectory.json", repo_root)
    manifest = result.get("validation_dependencies")
    if isinstance(manifest, dict):
        result["validation_dependencies"] = merge_review_dependencies(manifest, observed)
    _write_json(output_dir / "review.json", result)
    return result


def _validate_protocol_contract_shape(
    contract: dict[str, Any],
    repo_root: Path,
    entrypoints: list[dict[str, Any]],
    *,
    label: str,
) -> None:
    expected = set(PROTOCOL_CONTRACT_FIELDS)
    if set(contract) != expected:
        raise ValueError(f"{label} must contain exactly the eight protocol contract fields")
    for field in (
        "capability_family",
        "semantic_domain",
        "extension_trigger",
        "downstream_guarantee",
        "boundary",
    ):
        if not isinstance(contract.get(field), str) or not contract[field].strip():
            raise ValueError(f"{label}.{field} must be a non-empty string")
    variants = contract.get("covered_variants")
    if not isinstance(variants, list) or not variants or not all(
        isinstance(item, str) and item.strip() for item in variants
    ):
        raise ValueError(f"{label}.covered_variants must be a non-empty string list")

    root = repo_root.resolve()
    consumers = contract.get("consumers")
    if not isinstance(consumers, list) or len(consumers) < 2:
        raise ValueError(f"{label}.consumers must contain at least two source consumers")
    consumer_keys = []
    for consumer in consumers:
        if not isinstance(consumer, dict):
            raise ValueError(f"{label}.consumers entries must be objects")
        file_id, unit_id, role = (
            consumer.get("file_id"),
            consumer.get("unit_id"),
            consumer.get("role"),
        )
        if (
            not isinstance(file_id, str)
            or not file_id
            or Path(file_id).is_absolute()
            or ".." in Path(file_id).parts
            or not isinstance(unit_id, str)
            or not unit_id.strip()
            or not isinstance(role, str)
            or not role.strip()
        ):
            raise ValueError(f"{label}.consumers contains a malformed source consumer")
        source_path = (root / file_id).resolve()
        if root not in source_path.parents or not source_path.is_file():
            raise ValueError(f"{label}.consumer does not resolve inside repository: {file_id}")
        consumer_keys.append((file_id, unit_id))
    if len(consumer_keys) != len(set(consumer_keys)):
        raise ValueError(f"{label}.consumers contains duplicate source units")

    reuse = contract.get("reuse_interface")
    if not isinstance(reuse, dict) or set(reuse) != {"mode", "value"}:
        raise ValueError(f"{label}.reuse_interface must contain mode and value")
    if reuse.get("mode") not in {"stable_entrypoint", "reference_pattern"}:
        raise ValueError(f"{label}.reuse_interface has an unsupported mode")
    if not isinstance(reuse.get("value"), str) or not reuse["value"].strip():
        raise ValueError(f"{label}.reuse_interface.value must be a non-empty string")
    if reuse["mode"] == "stable_entrypoint":
        names = {
            item.get("name")
            for item in entrypoints
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if reuse["value"] not in names:
            raise ValueError(f"{label}.reuse_interface.value is not a declared entrypoint")


def _protocol_review_scope(
    candidate_payload: dict[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    scope = candidate_payload.get("protocol_review_scope")
    if scope is None:
        return PROTOCOL_CONTRACT_FIELDS, None
    if not isinstance(scope, dict):
        raise ValueError("protocol_review_scope must be an object")
    fields = scope.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(field, str) for field in fields)
        or len(fields) != len(set(fields))
        or not set(fields) <= set(PROTOCOL_CONTRACT_FIELDS)
    ):
        raise ValueError("protocol_review_scope.fields must be unique protocol fields")
    previous = scope.get("previous_review")
    is_full_review = set(fields) == set(PROTOCOL_CONTRACT_FIELDS)
    if not is_full_review and not isinstance(previous, dict):
        raise ValueError("scoped protocol verification requires previous_review")
    return (
        tuple(field for field in PROTOCOL_CONTRACT_FIELDS if field in fields),
        None if is_full_review else previous,
    )


def protocol_review_blocks_publication(review: dict[str, Any]) -> bool:
    """Return whether a protocol decision should keep a component unpublished."""
    status = review.get("status")
    if status in {"needs_revision", "rejected"}:
        return True
    return any(
        isinstance(issue, dict) and issue.get("severity", "blocking") == "blocking"
        for issue in review.get("field_issues", [])
    )


def materialize_protocol_contract_revision(
    protocol_contract: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    """Apply a review's field-level revision without asking an agent to rewrite all fields."""
    revised = review.get("revised_contract")
    if isinstance(revised, dict) and revised:
        return deepcopy(revised)
    revisions = review.get("field_revisions", {})
    if not isinstance(revisions, dict):
        raise ValueError("protocol review field_revisions must be an object")
    materialized = deepcopy(protocol_contract)
    materialized.update(deepcopy(revisions))
    return materialized


def merge_protocol_contract_reviews(
    previous: dict[str, Any],
    scoped: dict[str, Any],
) -> dict[str, Any]:
    """Replace only re-reviewed field decisions and keep all other fields closed."""
    reviewed = scoped.get("reviewed_fields")
    if not isinstance(reviewed, list) or not reviewed:
        raise ValueError("scoped protocol review must declare reviewed_fields")
    reviewed_set = set(reviewed)
    previous_issues = [
        deepcopy(issue)
        for issue in previous.get("field_issues", [])
        if isinstance(issue, dict) and issue.get("field") not in reviewed_set
    ]
    scoped_issues = [
        deepcopy(issue)
        for issue in scoped.get("field_issues", [])
        if isinstance(issue, dict)
    ]
    issues = [*previous_issues, *scoped_issues]
    issue_fields = {issue.get("field") for issue in issues}
    confirmed = [field for field in PROTOCOL_CONTRACT_FIELDS if field not in issue_fields]

    revisions: dict[str, Any] = {}
    for source in (previous, scoped):
        values = source.get("field_revisions")
        if isinstance(values, dict):
            for field, value in values.items():
                if source is scoped or field not in reviewed_set:
                    revisions[field] = deepcopy(value)
    previous_revised = previous.get("revised_contract")
    if isinstance(previous_revised, dict):
        for field in issue_fields - reviewed_set:
            if field in previous_revised:
                revisions.setdefault(field, deepcopy(previous_revised[field]))
    blocking = any(issue.get("severity", "blocking") == "blocking" for issue in issues)
    previous_rejected_is_locked = previous.get("status") == "rejected" and any(
        issue.get("field") not in reviewed_set
        and issue.get("severity", "blocking") == "blocking"
        for issue in previous_issues
    )
    rejected = scoped.get("status") == "rejected" or previous_rejected_is_locked
    status = (
        "rejected"
        if rejected
        else "needs_revision"
        if blocking
        else "confirmed_with_warnings"
        if issues
        else "confirmed"
    )
    if rejected:
        revisions = {}
    return {
        "schema_version": 2,
        "status": status,
        "reason": scoped.get("reason") or previous.get("reason") or "Protocol fields reviewed.",
        "reviewed_fields": list(PROTOCOL_CONTRACT_FIELDS),
        "confirmed_fields": confirmed,
        "field_issues": issues,
        "field_revisions": revisions,
    }


def _validate_protocol_contract_review(
    result: dict[str, Any],
    protocol_contract: dict[str, Any],
    repo_root: Path,
    entrypoints: list[dict[str, Any]],
    *,
    artifact_content: str | None = None,
    review_fields: tuple[str, ...] | None = None,
    require_schema_version: int | None = None,
) -> None:
    _validate_protocol_contract_shape(
        protocol_contract,
        repo_root,
        entrypoints,
        label="protocol_contract",
    )
    review = result.get("protocol_contract_review")
    if not isinstance(review, dict):
        raise ValueError("component review must include protocol_contract_review")
    status = review.get("status")
    if status not in PROTOCOL_CONTRACT_REVIEW_STATUSES:
        raise ValueError("protocol_contract_review returned an invalid status")
    if not isinstance(review.get("reason"), str) or not review["reason"].strip():
        raise ValueError("protocol_contract_review must include a reason")

    confirmed = review.get("confirmed_fields")
    issues = review.get("field_issues")
    schema_version = review.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise ValueError("protocol_contract_review has an unsupported schema_version")
    if require_schema_version is not None and schema_version != require_schema_version:
        raise ValueError(
            f"protocol_contract_review must use schema_version {require_schema_version}"
        )
    expected_fields = set(review_fields or PROTOCOL_CONTRACT_FIELDS)
    reviewed = review.get("reviewed_fields", list(PROTOCOL_CONTRACT_FIELDS))
    if (
        not isinstance(reviewed, list)
        or any(not isinstance(item, str) for item in reviewed)
        or len(reviewed) != len(set(reviewed))
        or set(reviewed) != expected_fields
    ):
        raise ValueError("protocol_contract_review.reviewed_fields does not match the requested scope")
    revised = review.get("revised_contract", {})
    field_revisions = review.get("field_revisions", {})
    if not isinstance(confirmed, list) or not all(isinstance(item, str) for item in confirmed):
        raise ValueError("protocol_contract_review.confirmed_fields must be a string list")
    if len(confirmed) != len(set(confirmed)):
        raise ValueError("protocol_contract_review.confirmed_fields contains duplicates")
    if (
        not isinstance(issues, list)
        or not isinstance(revised, dict)
        or not isinstance(field_revisions, dict)
    ):
        raise ValueError("protocol_contract_review issues or revisions are malformed")
    if revised and field_revisions:
        raise ValueError("protocol_contract_review cannot use both revision formats")

    confirmed_set = set(confirmed)
    if not confirmed_set <= expected_fields:
        raise ValueError("protocol_contract_review confirmed an unknown field")
    issue_fields = set()
    blocking_fields = set()
    warning_fields = set()
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("protocol_contract_review field issue must be an object")
        field = issue.get("field")
        if field not in expected_fields:
            raise ValueError("protocol_contract_review has an issue outside the requested scope")
        if issue.get("status") not in PROTOCOL_CONTRACT_ISSUE_STATUSES:
            raise ValueError("protocol_contract_review field issue has an invalid status")
        severity = issue.get("severity")
        if schema_version == 1 and severity is None:
            severity = "blocking"
        if severity not in PROTOCOL_CONTRACT_ISSUE_SEVERITIES:
            raise ValueError("protocol_contract_review field issue has an invalid severity")
        if not isinstance(issue.get("issue"), str) or not issue["issue"].strip():
            raise ValueError("protocol_contract_review field issue must explain the problem")
        evidence = issue.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("protocol_contract_review field issue requires source evidence")
        artifact_file = f"{Path(COMPONENT_DIRECTORY).name}/common.py"
        if not any(
            isinstance(citation, dict)
            and Path(str(citation.get("file_id", ""))).as_posix() != artifact_file
            for citation in evidence
        ):
            raise ValueError("protocol contract field issue requires original repository evidence")
        _validate_review_result(
            {"status": "uncertain", "confirmed_members": [], "evidence": evidence},
            repo_root,
            artifact_content=artifact_content,
        )
        issue_fields.add(field)
        (blocking_fields if severity == "blocking" else warning_fields).add(field)
    if confirmed_set & issue_fields:
        raise ValueError("protocol contract fields cannot be both confirmed and disputed")
    if confirmed_set | issue_fields != expected_fields:
        raise ValueError("protocol_contract_review must account for every protocol field in the requested scope")

    if status == "confirmed":
        legacy_revision = schema_version == 1 and revised in ({}, protocol_contract)
        if (
            issue_fields
            or confirmed_set != expected_fields
            or field_revisions
            or (schema_version == 2 and revised)
            or (schema_version == 1 and not legacy_revision)
        ):
            raise ValueError("confirmed protocol contract review cannot contain field revisions")
    elif status == "confirmed_with_warnings":
        if not warning_fields or blocking_fields or revised or field_revisions:
            raise ValueError("confirmed_with_warnings requires warning issues and no revisions")
    elif status == "needs_revision":
        if not blocking_fields:
            raise ValueError("needs_revision protocol contract review requires blocking issues")
        if schema_version == 2 and set(field_revisions) != blocking_fields:
            raise ValueError("field_revisions must contain exactly the blocking fields")
        if schema_version == 1 and not revised:
            raise ValueError("legacy needs_revision review requires a revised_contract")
        materialized = materialize_protocol_contract_revision(protocol_contract, review)
        _validate_protocol_contract_shape(
            materialized,
            repo_root,
            entrypoints,
            label="protocol_contract_review.materialized_contract",
        )
    elif not blocking_fields or revised or field_revisions:
        raise ValueError("rejected protocol contract review requires blocking issues and no revisions")


def _checked_citations(response: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    citations = response.get("sources")
    if not isinstance(citations, list) or not citations:
        raise ValueError("validation agent returned no repository source citations")
    checked: list[dict[str, Any]] = []
    root = repo_root.resolve()
    for citation in citations:
        if not isinstance(citation, dict):
            raise ValueError("validation citation must be an object")
        file_id = citation.get("file_id")
        line_start, line_end = citation.get("line_start"), citation.get("line_end")
        role = citation.get("role")
        if (
            not isinstance(file_id, str)
            or not file_id
            or Path(file_id).is_absolute()
            or ".." in Path(file_id).parts
            or not isinstance(line_start, int)
            or isinstance(line_start, bool)
            or not isinstance(line_end, int)
            or isinstance(line_end, bool)
            or line_start < 1
            or line_end < line_start
            or role not in {"test", "fixture", "production_call", "interface_contract"}
        ):
            raise ValueError("validation agent returned a malformed source citation")
        source_path = (root / file_id).resolve()
        if Path(file_id).parts[:1] == (Path(COMPONENT_DIRECTORY).name,):
            raise ValueError("validation citations must reference original repository sources")
        if root not in source_path.parents or not source_path.is_file():
            raise ValueError(f"validation citation does not resolve inside repository: {file_id}")
        try:
            line_count = len(source_path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot read cited source file {file_id}: {exc}") from exc
        if line_end > line_count:
            raise ValueError(f"validation citation exceeds the end of {file_id}")
        checked.append({
            "file_id": Path(file_id).as_posix(),
            "line_start": line_start,
            "line_end": line_end,
            "role": role,
        })
    return checked



def _validate_review_result(
    review: dict[str, Any], repo_root: Path, *, artifact_content: str | None = None,
) -> None:
    members = review.get("confirmed_members")
    evidence = review.get("evidence")
    if not isinstance(members, list) or not isinstance(evidence, list):
        raise ValueError("commonality review must include member and evidence lists")
    if review.get("status") == "confirmed" and (not members or not evidence):
        raise ValueError("confirmed commonality review requires members and evidence")
    root = repo_root.resolve()
    for member in members:
        if not isinstance(member, dict):
            raise ValueError("commonality review member must be an object")
        file_id, unit_id = member.get("file_id"), member.get("unit_id")
        if (
            not isinstance(file_id, str)
            or not file_id
            or Path(file_id).is_absolute()
            or ".." in Path(file_id).parts
            or not isinstance(unit_id, str)
        ):
            raise ValueError("commonality review returned a malformed member")
        source_path = (root / file_id).resolve()
        if Path(file_id).parts[:1] == (Path(COMPONENT_DIRECTORY).name,):
            raise ValueError("commonality review members must reference original repository sources")
        if root not in source_path.parents or not source_path.is_file():
            raise ValueError(f"commonality review member is outside repository: {file_id}")
    for citation in evidence:
        if not isinstance(citation, dict):
            raise ValueError("commonality review evidence must be an object")
        file_id = citation.get("file_id")
        start, end = citation.get("line_start"), citation.get("line_end")
        if (
            not isinstance(file_id, str)
            or not file_id
            or Path(file_id).is_absolute()
            or ".." in Path(file_id).parts
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
            or not isinstance(citation.get("claim"), str)
            or not citation["claim"].strip()
        ):
            raise ValueError("commonality review returned malformed evidence")
        artifact_file = f"{Path(COMPONENT_DIRECTORY).name}/common.py"
        if Path(file_id).as_posix() == artifact_file and isinstance(artifact_content, str):
            # This mount is separate from the host repository. Check the exact
            # submitted artifact rather than trusting an unrelated host file.
            line_count = len(artifact_content.splitlines())
        else:
            source_path = (root / file_id).resolve()
            if (
                Path(file_id).parts[:1] == (Path(COMPONENT_DIRECTORY).name,)
                or root not in source_path.parents or not source_path.is_file()
            ):
                raise ValueError(f"commonality review citation is outside repository: {file_id}")
            try:
                line_count = len(source_path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"cannot read review citation {file_id}: {exc}") from exc
        if end > line_count:
            raise ValueError(f"commonality review citation exceeds the end of {file_id}")



def _validate_review_member_boundary(
    review: dict[str, Any],
    component: dict[str, Any],
    candidate_payload: dict[str, Any],
) -> None:
    if review.get("status") != "confirmed":
        return
    proposed = component.get("component_draft") or component.get("agent_extraction") or component
    allowed: set[tuple[str, str]] = set()

    def add_members(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            if isinstance(item, dict):
                file_id, unit_id = item.get("file_id"), item.get("unit_id")
                if isinstance(file_id, str) and isinstance(unit_id, str):
                    allowed.add((file_id, unit_id))

    candidate = candidate_payload.get("candidate", {})
    if isinstance(candidate, dict):
        add_members(candidate.get("members"))
        add_members(candidate.get("interfaces"))
    add_members(proposed.get("members") if isinstance(proposed, dict) else None)
    confirmed = review.get("confirmed_members", [])
    if not confirmed:
        raise ValueError("component validation has no scoped members")
    for item in confirmed:
        pair = (item.get("file_id"), item.get("unit_id")) if isinstance(item, dict) else None
        if pair not in allowed:
            raise ValueError("reviewer added a member outside the candidate and extracted draft")



def _component_fields(component: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    extraction = (
        component.get("component_draft")
        or component.get("agent_extraction")
        or component.get("extraction")
        or component
    )
    if not isinstance(extraction, dict) or extraction.get("status") != "draft_ready":
        raise ValueError("component has no draft_ready extraction")
    library = extraction.get("library")
    content = library.get("content") if isinstance(library, dict) else None
    entrypoints = extraction.get("entrypoints")
    limitations = extraction.get("limitations", component.get("limitations", []))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("component library is empty")
    if not isinstance(entrypoints, list) or not entrypoints:
        raise ValueError("component has no declared entrypoints")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise ValueError("component limitations must be a list of strings")
    return content, entrypoints, limitations


def validate_component(
    *,
    component_id: str,
    component: dict[str, Any],
    candidate_payload: dict[str, Any],
    repository: RepositoryContext,
    agent_runner: Any,
    output_dir: Path,
    runtime_timeout: int = 60,
    review: dict[str, Any] | None = None,
    sources: dict[str, str] | None = None,
    grounding_members: list[str] | None = None,
    experiment_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Consume one combined review, then execute its grounded smoke test."""
    from component_method.component_build.validation.artifact_service import extraction_record, validate_artifact_component

    if "artifact" in extraction_record(component):
        return validate_artifact_component(
            component_id=component_id, component=component, candidate_payload=candidate_payload,
            repository=repository, agent_runner=agent_runner, output_dir=output_dir,
            runtime_timeout=runtime_timeout, review=review,
        )
    repo_root = repository.resolved_root()
    output_dir.mkdir(parents=True, exist_ok=True)

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        if isinstance(review, dict):
            result.setdefault("commonality_review", review)
            result.setdefault("artifact_review", review.get("artifact_review"))
            result.setdefault("smoke_plan", review.get("smoke_test"))
            if isinstance(review.get("entrypoint_capabilities"), list):
                result.setdefault("entrypoint_capabilities", [
                    {**cap, "validation_status": "missing" if cap.get("availability") == "missing" else "unverified"}
                    for cap in review["entrypoint_capabilities"] if isinstance(cap, dict)
                ])
        _write_json(output_dir / "validation.json", result)
        return result
    if review is None:
        try:
            review_payload = dict(candidate_payload)
            extraction = component.get("component_draft") or component.get("agent_extraction") or component
            review_payload["proposed_component"] = extraction
            review = review_component(
                agent_runner,
                review_payload,
                output_dir / "commonality_review",
                repo_root=repo_root,
                experiment_dir=experiment_dir,
            )
        except Exception as exc:
            return finish({
                "schema": VALIDATION_RESULT_SCHEMA,
                "component_id": component_id,
                "status": "uncertain",
                "reason": f"commonality review failed: {type(exc).__name__}: {exc}",
            })
    try:
        extraction = component.get("component_draft") or component.get("agent_extraction") or component
        library = extraction.get("library", {}) if isinstance(extraction, dict) else {}
        artifact_content = library.get("content") if isinstance(library, dict) else None
        _validate_review_result(review, repo_root, artifact_content=artifact_content)
        _validate_review_member_boundary(review, component, candidate_payload)
    except Exception as exc:
        return finish({
            "schema": VALIDATION_RESULT_SCHEMA,
            "component_id": component_id,
            "status": "uncertain",
            "reason": f"commonality review failed validation: {type(exc).__name__}: {exc}",
            "commonality_review": review,
        })
    if review.get("status") != "confirmed":
        return finish({
            "schema": VALIDATION_RESULT_SCHEMA,
            "component_id": component_id,
            "status": "rejected" if review.get("status") == "rejected" else "uncertain",
            "reason": review.get("reason", "component was not confirmed reusable"),
            "commonality_review": review,
        })

    artifact_review = review.get("artifact_review")
    if not isinstance(artifact_review, dict) or artifact_review.get("status") != "faithful":
        artifact_status = artifact_review.get("status") if isinstance(artifact_review, dict) else None
        return finish({
            "schema": VALIDATION_RESULT_SCHEMA,
            "component_id": component_id,
            "status": "failed" if artifact_status == "invalid" else "unverified",
            "reason": (
                artifact_review.get("reason") or "artifact fidelity was not established"
                if isinstance(artifact_review, dict)
                else "combined review has no artifact fidelity decision"
            ),
        })

    try:
        library_content, entrypoints, limitations = _component_fields(component)
    except ValueError as exc:
        return finish({
            "schema": VALIDATION_RESULT_SCHEMA,
            "component_id": component_id,
            "status": "failed",
            "reason": str(exc),
            "commonality_review": review,
        })

    agent_dir = output_dir / "smoke_plan"
    agent_dir.mkdir(parents=True, exist_ok=True)
    try:
        response = review.get("smoke_test")
        if not isinstance(response, dict):
            raise ValueError("combined review has no smoke-test plan")
        _write_json(agent_dir / "plan.json", response)
        if response.get("status") != "ready":
            return finish({
                "schema": VALIDATION_RESULT_SCHEMA,
                "component_id": component_id,
                "status": "unverified",
                "reason": response.get("reason", "no grounded smoke cases were found"),
                "commonality_review": review,
                "test_source": "combined_review",
            })
        if "entrypoint_capabilities" not in review:
            # Historical reviews used a single smoke script. Current reviews
            # supply independent cases, whose code and citations are checked below.
            test_content = response.get("test_py")
            if not isinstance(test_content, str) or not test_content.strip():
                raise ValueError("combined review returned no test.py source")
            citations = _checked_citations(response, repo_root)
    except Exception as exc:
        _write_json(agent_dir / "agent_error.json", {"error": f"{type(exc).__name__}: {exc}"})
        return finish({
            "schema": VALIDATION_RESULT_SCHEMA,
            "component_id": component_id,
            "status": "unverified",
            "reason": f"test planning failed: {type(exc).__name__}: {exc}",
            "commonality_review": review,
            "test_source": "combined_review",
        })

    reviewed_paths = {
        item.get("file_id")
        for item in review.get("confirmed_members", [])
        if isinstance(item, dict) and isinstance(item.get("file_id"), str)
    }
    member_paths = sorted(reviewed_paths & set(grounding_members)) if grounding_members else sorted(reviewed_paths)
    if "entrypoint_capabilities" in review:
        return _validate_capability_cases(
            component_id, review, response, library_content, entrypoints, limitations,
            repo_root, output_dir, repository, runtime_timeout, member_paths, sources,
        )
    (agent_dir / "test.py").write_text(test_content, encoding="utf-8")
    _write_json(agent_dir / "test_sources.json", citations)
    check = validate_callable_artifact(
        component_id=component_id,
        library_content=library_content,
        smoke_content=test_content,
        entrypoints=entrypoints,
        repo_root=repo_root,
        output_dir=output_dir / "runtime_validation",
        timeout_seconds=runtime_timeout,
        runtime_image=repository.runtime_image,
        runtime_activation=repository.runtime_activation,
        container_manager=repository.container_manager,
        container=repository.container,
        container_workdir=repository.container_workdir,
        grounding_members=member_paths,
        all_sources=sources,
    )
    check["schema"] = VALIDATION_RESULT_SCHEMA
    check["test_sources"] = citations
    check["commonality_review"] = review
    check["artifact_review"] = artifact_review
    check["smoke_plan"] = response
    check["test_source"] = "combined_review"
    check["limitations"] = limitations
    check["repository"] = repository.to_json()
    check["status"] = "validated" if check.get("status") == "ok" else "failed"
    _write_json(output_dir / "validation.json", check)

    if check["status"] == "validated":
        validated_dir = output_dir / "validated"
        validated_dir.mkdir(parents=True, exist_ok=True)
        (validated_dir / "common.py").write_text(library_content, encoding="utf-8")
        (validated_dir / "test.py").write_text(test_content, encoding="utf-8")
        _write_json(validated_dir / "validation.json", check)
        _write_json(validated_dir / "test_sources.json", citations)
    return check


from component_method.languages.python.observation import (
    _smoke_call_constants, _case_exercises_path, _runtime_exercises_path,
    _unreported_class_paths, _capability_path,
)

def _validate_capability_cases(
    component_id, review, plan, library_content, entrypoints, limitations,
    repo_root, output_dir, repository, timeout, member_paths, sources,
):
    """Isolate declaration/case errors and retain independently validated paths."""
    declarations = review.get("entrypoint_capabilities")
    cases = plan.get("cases")
    names = {entry["name"]: entry for entry in entrypoints}
    if not isinstance(declarations, list) or not declarations or not isinstance(cases, list):
        result = {
            "schema": VALIDATION_RESULT_SCHEMA, "component_id": component_id,
            "status": "unverified", "reason": "entrypoint capabilities and independent smoke cases are required",
            "commonality_review": review, "artifact_review": review.get("artifact_review"), "smoke_plan": plan,
        }
        _write_json(output_dir / "validation.json", result)
        return result

    capabilities, declaration_errors, case_errors = [], [], []
    seen = set()
    for index, cap in enumerate(declarations):
        record = dict(cap) if isinstance(cap, dict) else {"path": "", "case_ids": []}
        try:
            if not isinstance(cap, dict):
                raise ValueError("capability declaration must be an object")
            record["path"] = _capability_path(cap, names)
            case_ids = cap.get("case_ids")
            if not isinstance(case_ids, list) or not all(isinstance(x, str) for x in case_ids):
                raise ValueError("capability case_ids must be a list of strings")
            identity = (record["entrypoint"], record["path"], tuple(sorted(case_ids)))
            if identity in seen:
                raise ValueError("duplicate entrypoint capability declaration")
            if cap.get("availability") not in {"implemented", "missing", "unverified"}:
                raise ValueError("invalid capability availability")
            if not all(isinstance(cap.get(k), str) for k in ("contract", "example", "scope", "reason")):
                raise ValueError("capability contract, example, scope and reason must be strings")
            seen.add(identity)
        except (ValueError, TypeError, KeyError) as exc:
            # Retain the error on this record. It cannot make an unrelated path fail.
            record["path"] = record.get("path") if isinstance(record.get("path"), str) else ""
            record["validation_status"] = "unverified"
            record["runtime_reasons"] = [str(exc)]
            declaration_errors.append({"index": index, "reason": str(exc)})
        capabilities.append(record)

    case_map, results = {}, {}
    duplicate_ids = {case_id for case_id in (
        case.get("case_id") for case in cases if isinstance(case, dict)
    ) if isinstance(case_id, str) and sum(
        isinstance(case, dict) and case.get("case_id") == case_id for case in cases
    ) > 1}
    for index, case in enumerate(cases):
        case_id = case.get("case_id") if isinstance(case, dict) else None
        try:
            if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
                raise ValueError("smoke case requires an ASCII identifier")
            if case_id in duplicate_ids:
                raise ValueError("smoke case ID is duplicated")
            if not isinstance(case.get("entrypoint"), str) or case["entrypoint"] not in names:
                raise ValueError("smoke case entrypoint is outside the extracted draft")
            if not isinstance(case.get("test_py"), str) or not case["test_py"].strip():
                raise ValueError("smoke case has no executable test")
            case_map[case_id] = case
            try:
                _checked_citations(case, repo_root)
            except ValueError as exc:
                results[case_id] = {"status": "invalid_citations", "reason": str(exc)}
        except (ValueError, TypeError, AttributeError) as exc:
            case_errors.append({"index": index, "case_id": case_id, "reason": str(exc)})

    active = set()
    for cap in capabilities:
        if "validation_status" in cap:
            continue
        wrong_ids = [case_id for case_id in cap["case_ids"]
                     if case_id not in case_map or case_map[case_id]["entrypoint"] != cap["entrypoint"]]
        if wrong_ids:
            cap["validation_status"] = "missing" if cap["availability"] == "missing" else "unverified"
            cap["runtime_reasons"] = ["case IDs must refer to unique cases for the same entrypoint: " + ", ".join(wrong_ids)]
            continue
        if cap["availability"] == "implemented":
            active.update(cap["case_ids"])
    for case_id in sorted(active):
        if case_id in results:
            continue
        case = case_map[case_id]
        try:
            results[case_id] = validate_callable_artifact(
                component_id=component_id, library_content=library_content,
                smoke_content=case["test_py"], entrypoints=[names[case["entrypoint"]]],
                repo_root=repo_root, output_dir=output_dir / "runtime_validation" / case_id,
                timeout_seconds=timeout, runtime_image=repository.runtime_image,
                runtime_activation=repository.runtime_activation,
                container_manager=repository.container_manager, container=repository.container,
                container_workdir=repository.container_workdir, grounding_members=member_paths,
                all_sources=sources,
            )
        except Exception as exc:
            results[case_id] = {"status": "execution_error", "reason": f"{type(exc).__name__}: {exc}"}
    for cap in capabilities:
        if "validation_status" in cap:
            continue
        statuses = [results[case_id]["status"] for case_id in cap["case_ids"] if case_id in results]
        exercised = all(_runtime_exercises_path(results.get(c, {}), cap["entrypoint"], cap["path"])
                        for c in cap["case_ids"])
        cap["validation_status"] = (
            "missing" if cap["availability"] == "missing" else
            "unverified" if cap["availability"] != "implemented" or not statuses or not exercised or "invalid_citations" in statuses else
            "validated" if all(status == "ok" for status in statuses) else "failed"
        )
        cap["runtime_reasons"] = [results[c].get("reason", "") for c in cap["case_ids"] if c in results and results[c]["status"] != "ok"]
        if statuses and not exercised:
            cap["runtime_reasons"].append("Smoke cases do not exercise the declared method or input mode")
    represented = {cap.get("entrypoint") for cap in capabilities if isinstance(cap.get("entrypoint"), str)}
    for name in sorted(set(names) - represented):
        capabilities.append({"entrypoint": name, "path": name, "availability": "unverified",
                             "validation_status": "unverified", "contract": "", "example": "", "scope": "",
                             "reason": "No capability scope was declared", "case_ids": [], "runtime_reasons": []})
    capabilities.extend(_unreported_class_paths(library_content, entrypoints, capabilities))
    usable = any(cap["validation_status"] == "validated" for cap in capabilities)
    result = {
        "schema": VALIDATION_RESULT_SCHEMA, "component_id": component_id,
        "status": "validated" if usable else "failed",
        "reason": "Usable paths are limited to the independently validated capabilities",
        "entrypoint_capabilities": capabilities, "case_results": results,
        "declaration_errors": declaration_errors, "case_errors": case_errors,
        "commonality_review": review, "artifact_review": review.get("artifact_review"),
        "smoke_plan": plan, "test_source": "combined_review", "limitations": limitations,
        "repository": repository.to_json(),
    }
    _write_json(output_dir / "validation.json", result)
    if usable:
        validated = output_dir / "validated"
        validated.mkdir(parents=True, exist_ok=True)
        (validated / "common.py").write_text(library_content, encoding="utf-8")
        passing = [case_map[c]["test_py"] for c in sorted(active) if results[c]["status"] == "ok"]
        aggregate = "def run(common):\n"
        for i, code in enumerate(passing):
            aggregate += f"    namespace_{i} = {{'__name__': __name__, '__file__': __file__}}\n    exec({code!r}, namespace_{i})\n    result_{i} = namespace_{i}['run'](common)\n    if __import__('inspect').isawaitable(result_{i}):\n        result_{i} = __import__('asyncio').run(result_{i})\n    assert result_{i} is not False\n"
        aggregate += "    return True\n"
        (validated / "test.py").write_text(aggregate, encoding="utf-8")
        _write_json(validated / "validation.json", result)
    return result
