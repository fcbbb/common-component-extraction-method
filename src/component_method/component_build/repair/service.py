"""Constrained repair agent for already-confirmed reusable components."""

from __future__ import annotations

import ast
from copy import deepcopy
import difflib
import json
from pathlib import Path
from typing import Any

from ..contracts import normalize_component_draft, validate_component_draft
from ..workspace import COMPONENT_DIRECTORY
from ..validation.service import (
    _checked_citations,
    _validate_protocol_contract_review,
    _validate_protocol_contract_shape,
    _validate_review_member_boundary,
    _validate_review_result,
)


REPAIR_TARGETS = {
    "review_manifest",
    "protocol_contract",
    "component_evidence",
    "artifact",
    "smoke_failure",
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _component_brief(component: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in component.items()
        if key != "library"
    }


def _repair_prompt(request: dict[str, Any]) -> str:
    target = request["repair_target"]
    common = (
        "Repair one already-confirmed reusable component. The original repository is read-only at "
        "/testbed. The current extracted artifact is read-only at " + COMPONENT_DIRECTORY + "/common.py, "
        "with metadata at " + COMPONENT_DIRECTORY + "/component.json, the request at "
        + COMPONENT_DIRECTORY + "/repair_request.json, and the previous review at "
        + COMPONENT_DIRECTORY + "/review.json when supplied. Do not change the original repository. "
        "Do not change component identity, members, capability purpose or declared entrypoints. Do not decide "
        "whether the component is reusable and do not claim that your own repair is approved. Inspect source "
        "only as needed to implement the supplied repair request.\n\n"
    )
    if target == "protocol_contract":
        instructions = (
            "Return a complete replacement protocol_contract. Change only the exact fields listed in "
            "allowed_protocol_fields; copy every other field exactly. Every statement must remain task-blind "
            "and source-grounded. The replacement must keep the existing eight-field schema, at least two "
            "source consumers, and a valid single stable_entrypoint or reference_pattern reuse interface."
        )
        schema = {
            "status": "repaired|not_repairable",
            "repair_target": "protocol_contract",
            "reason": "",
            "changes": ["field: concise change"],
            "protocol_contract": "complete eight-field object when repaired",
        }
    elif target == "review_manifest":
        instructions = (
            "Correct only the validation defects listed in allowed_review_changes. Preserve all substantive "
            "decisions, reasons, claims, members, limitations, capability declarations, test code and protocol "
            "field judgments. For citation_line_ranges, inspect the exact files and correct line_start/line_end. "
            "For citation_file_paths, replace only the explicitly allowed invalid original citation paths with "
            "the real repository source that supports the unchanged claim. For "
            "protocol_review_empty_revised_contract, only add the empty revised_contract required by a confirmed "
            "protocol judgment. For protocol_review_revised_fields, change only the revised_contract fields named "
            "in allowed_protocol_review_fields; preserve the status, reason, confirmed fields, issues and evidence. "
            "For protocol_review_merge_duplicate_issues, merge repeated entries for the same protocol field into "
            "one entry while preserving every original issue statement and citation. For confirmed_member_boundary, "
            "remove only confirmed_members that are outside the supplied component boundary. "
            "Return the complete corrected review. Write every smoke "
            "case to a separate .py file and reference it with test_file."
        )
        schema = {
            "status": "repaired|not_repairable",
            "repair_target": "review_manifest",
            "reason": "",
            "changes": ["citation: concise correction"],
            "review": "complete corrected review object when repaired",
        }
    elif target == "component_evidence":
        instructions = (
            "Return a complete replacement evidence list. Preserve every existing evidence entry exactly and "
            "in the same order, then append only the missing source citations requested in required_evidence_files. "
            "Do not add citations for any other files. Each appended citation must use a real repository-relative "
            "file_id, valid line_start/line_end, and a source-grounded claim. Do not change any other component field."
        )
        schema = {
            "status": "repaired|not_repairable",
            "repair_target": "component_evidence",
            "reason": "",
            "changes": ["evidence: concise addition"],
            "evidence": "complete original evidence list followed by requested additions when repaired",
        }
    else:
        instructions = (
            "Write a complete repaired Python artifact. Make only the smallest changes needed for the listed "
            "artifact or smoke failure. Preserve declared entrypoint names and behavior, and do not add relative "
            "imports because the artifact is delivered outside the original package."
        )
        schema = {
            "status": "repaired|not_repairable",
            "repair_target": target,
            "reason": "",
            "changes": ["code: concise correction"],
            "library": {"path": "repaired/common.py"},
        }
    return (
        common
        + instructions
        + "\n\nRepair request:\n"
        + json.dumps({key: value for key, value in request.items() if key != "previous_review"}, ensure_ascii=False, indent=2)
        + "\n\nWrite manifest.json matching this envelope:\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )


def _review_without_allowed_changes(
    value: Any,
    allowed: set[str],
    *,
    protocol_fields: set[str],
    path: tuple[str, ...] = (),
) -> Any:
    if isinstance(value, list):
        return [
            _review_without_allowed_changes(
                item,
                allowed,
                protocol_fields=protocol_fields,
                path=path,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    citation = "file_id" in value and "line_start" in value and "line_end" in value
    omitted = {"test_file"}
    if "citation_line_ranges" in allowed:
        omitted.update({"line_start", "line_end"})
    if citation and "citation_file_paths" in allowed:
        omitted.add("file_id")
    if path == ("protocol_contract_review",):
        if "protocol_review_empty_revised_contract" in allowed:
            omitted.add("revised_contract")
        if "protocol_review_merge_duplicate_issues" in allowed:
            omitted.add("field_issues")
    if path == ("protocol_contract_review", "revised_contract"):
        if "protocol_review_revised_fields" in allowed:
            omitted.update(protocol_fields)
    if path == () and "confirmed_member_boundary" in allowed:
        omitted.add("confirmed_members")
    return {
        key: _review_without_allowed_changes(
            item,
            allowed,
            protocol_fields=protocol_fields,
            path=(*path, key),
        )
        for key, item in value.items()
        if key not in omitted
    }


def _citation_file_changes(before: Any, after: Any) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    if isinstance(before, list) and isinstance(after, list):
        for left, right in zip(before, after):
            changes.extend(_citation_file_changes(left, right))
    elif isinstance(before, dict) and isinstance(after, dict):
        citation = all(key in before and key in after for key in ("file_id", "line_start", "line_end"))
        if citation and before["file_id"] != after["file_id"]:
            changes.append((before["file_id"], after["file_id"]))
        for key in before.keys() & after.keys():
            changes.extend(_citation_file_changes(before[key], after[key]))
    return changes


def _validate_review_repair(
    repaired: dict[str, Any],
    previous: dict[str, Any],
    component: dict[str, Any],
    repo_root: Path,
    request: dict[str, Any],
) -> None:
    allowed_values = request.get("allowed_review_changes")
    if not isinstance(allowed_values, list):
        raise ValueError("review repair requires allowed_review_changes")
    allowed = set(allowed_values)
    supported = {
        "citation_line_ranges",
        "citation_file_paths",
        "protocol_review_empty_revised_contract",
        "protocol_review_revised_fields",
        "protocol_review_merge_duplicate_issues",
        "confirmed_member_boundary",
    }
    if not allowed or not allowed <= supported:
        raise ValueError("review repair requested unsupported changes")
    if {
        "protocol_review_empty_revised_contract",
        "protocol_review_revised_fields",
    } <= allowed:
        raise ValueError("review repair requested conflicting protocol review changes")
    protocol_field_values = request.get("allowed_protocol_review_fields", [])
    if not isinstance(protocol_field_values, list) or any(
        not isinstance(field, str) for field in protocol_field_values
    ):
        raise ValueError("allowed_protocol_review_fields must be a string list")
    protocol_fields = set(protocol_field_values)
    if _review_without_allowed_changes(
        repaired,
        allowed,
        protocol_fields=protocol_fields,
    ) != _review_without_allowed_changes(
        previous,
        allowed,
        protocol_fields=protocol_fields,
    ):
        raise ValueError("review_manifest repair changed fields outside the approved scope")

    previous_protocol = previous.get("protocol_contract_review")
    repaired_protocol = repaired.get("protocol_contract_review")
    if "protocol_review_empty_revised_contract" in allowed:
        if (
            not isinstance(previous_protocol, dict)
            or previous_protocol.get("status") != "confirmed"
            or previous_protocol.get("revised_contract") not in (None, {})
            or not isinstance(repaired_protocol, dict)
            or repaired_protocol.get("revised_contract") != {}
            or protocol_fields
        ):
            raise ValueError("empty revised-contract repair is not a confirmed-review shape fix")
    if "protocol_review_revised_fields" in allowed:
        if not protocol_fields:
            raise ValueError("revised protocol review repair requires allowed fields")
        if (
            not isinstance(previous_protocol, dict)
            or previous_protocol.get("status") != "needs_revision"
            or not isinstance(previous_protocol.get("revised_contract"), dict)
            or not isinstance(repaired_protocol, dict)
            or not isinstance(repaired_protocol.get("revised_contract"), dict)
        ):
            raise ValueError("revised protocol review repair requires a needs_revision review")
        issue_fields = {
            issue.get("field")
            for issue in previous_protocol.get("field_issues", [])
            if isinstance(issue, dict)
        }
        if not protocol_fields <= issue_fields:
            raise ValueError("revised protocol review repair names a field without an existing issue")
        before_contract = previous_protocol["revised_contract"]
        after_contract = repaired_protocol["revised_contract"]
        changed = {
            field
            for field in set(before_contract) | set(after_contract)
            if before_contract.get(field) != after_contract.get(field)
        }
        if not changed or not changed <= protocol_fields:
            raise ValueError("revised protocol review repair changed an invalid field set")

    if "protocol_review_merge_duplicate_issues" in allowed:
        if not isinstance(previous_protocol, dict) or not isinstance(repaired_protocol, dict):
            raise ValueError("duplicate issue repair requires protocol review objects")
        before_issues = previous_protocol.get("field_issues")
        after_issues = repaired_protocol.get("field_issues")
        if not isinstance(before_issues, list) or not isinstance(after_issues, list):
            raise ValueError("duplicate issue repair requires issue lists")
        before_fields = [
            issue.get("field") for issue in before_issues if isinstance(issue, dict)
        ]
        if len(before_fields) != len(before_issues) or len(set(before_fields)) == len(before_fields):
            raise ValueError("duplicate issue repair found no duplicate protocol fields")
        expected_fields = list(dict.fromkeys(before_fields))
        after_fields = [issue.get("field") for issue in after_issues if isinstance(issue, dict)]
        if after_fields != expected_fields:
            raise ValueError("duplicate issue repair did not produce one ordered issue per field")
        for field in expected_fields:
            originals = [issue for issue in before_issues if issue["field"] == field]
            merged = next(issue for issue in after_issues if issue["field"] == field)
            if len(originals) == 1:
                if merged != originals[0]:
                    raise ValueError("duplicate issue repair changed a non-duplicate issue")
                continue
            if merged.get("status") not in {issue.get("status") for issue in originals}:
                raise ValueError("duplicate issue repair invented an issue status")
            merged_text = merged.get("issue")
            if not isinstance(merged_text, str) or any(
                issue.get("issue") not in merged_text for issue in originals
            ):
                raise ValueError("duplicate issue repair did not preserve every issue statement")
            expected_evidence = []
            for issue in originals:
                for citation in issue.get("evidence", []):
                    if citation not in expected_evidence:
                        expected_evidence.append(citation)
            if merged.get("evidence") != expected_evidence:
                raise ValueError("duplicate issue repair did not preserve the ordered evidence union")

    if "confirmed_member_boundary" in allowed:
        before_members = previous.get("confirmed_members")
        after_members = repaired.get("confirmed_members")
        component_members = component.get("members")
        if not all(isinstance(value, list) for value in (before_members, after_members, component_members)):
            raise ValueError("confirmed member-boundary repair requires member lists")
        allowed_keys = {
            (member.get("file_id"), member.get("unit_id"))
            for member in component_members if isinstance(member, dict)
        }
        expected_members = [
            member for member in before_members
            if isinstance(member, dict)
            and (member.get("file_id"), member.get("unit_id")) in allowed_keys
        ]
        if expected_members == before_members or after_members != expected_members:
            raise ValueError("confirmed member-boundary repair changed more than outside members")

    path_change_before = previous
    path_change_after = repaired
    if "protocol_review_merge_duplicate_issues" in allowed:
        path_change_before = deepcopy(previous)
        path_change_after = deepcopy(repaired)
        path_change_before["protocol_contract_review"]["field_issues"] = []
        path_change_after["protocol_contract_review"]["field_issues"] = []
    path_changes = _citation_file_changes(path_change_before, path_change_after)
    if "citation_file_paths" not in allowed and path_changes:
        raise ValueError("review_manifest repair changed a citation file path without permission")
    if "citation_file_paths" in allowed:
        permitted_originals = request.get("allowed_original_citation_files")
        if not isinstance(permitted_originals, list) or not permitted_originals:
            raise ValueError("citation file-path repair requires allowed_original_citation_files")
        if not path_changes or len(path_changes) > int(request.get("max_citation_file_path_changes", 1)):
            raise ValueError("review_manifest repair changed an invalid number of citation file paths")
        if any(original not in set(permitted_originals) for original, _ in path_changes):
            raise ValueError("review_manifest repair changed an unapproved original citation file path")
    content = component.get("library", {}).get("content")
    _validate_review_result(repaired, repo_root, artifact_content=content)
    payload = {"candidate": component, "proposed_component": component}
    _validate_review_member_boundary(repaired, component, payload)
    contract = component.get("protocol_contract")
    if isinstance(contract, dict):
        _validate_protocol_contract_review(
            repaired,
            contract,
            repo_root,
            component.get("entrypoints", []),
            artifact_content=content,
        )
    smoke = repaired.get("smoke_test")
    if isinstance(smoke, dict) and smoke.get("status") == "ready":
        for case in smoke.get("cases", []):
            _checked_citations({"sources": case.get("sources")}, repo_root)


def _validate_artifact_repair(
    content: str,
    component: dict[str, Any],
    *,
    max_changed_lines: int,
) -> None:
    tree = ast.parse(content)
    relative = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level]
    if relative:
        raise ValueError("repaired standalone artifact still contains relative imports")
    declared = {
        entry.get("name")
        for entry in component.get("entrypoints", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    if not declared <= defined:
        raise ValueError("repaired artifact removed a declared entrypoint")
    original = component.get("library", {}).get("content", "")
    changed = sum(
        1
        for line in difflib.ndiff(original.splitlines(), content.splitlines())
        if line.startswith(("- ", "+ "))
    )
    if changed > max_changed_lines:
        raise ValueError(f"artifact repair changed {changed} lines, above limit {max_changed_lines}")


def _validate_component_evidence_repair(
    replacement: Any,
    component: dict[str, Any],
    repo_root: Path,
    *,
    required_files: set[str],
    max_additions: int,
) -> None:
    original = component.get("evidence")
    if not isinstance(original, list) or not isinstance(replacement, list):
        raise ValueError("component evidence repair requires original and replacement evidence lists")
    if replacement[: len(original)] != original:
        raise ValueError("component evidence repair changed or reordered existing evidence")
    additions = replacement[len(original):]
    if not additions or len(additions) > max_additions:
        raise ValueError("component evidence repair added an invalid number of citations")
    added_files = {item.get("file_id") for item in additions if isinstance(item, dict)}
    if added_files != required_files:
        raise ValueError("component evidence repair did not add exactly the required evidence files")

    root = repo_root.resolve()
    for citation in additions:
        if not isinstance(citation, dict):
            raise ValueError("component evidence citation must be an object")
        file_id = citation.get("file_id")
        start = citation.get("line_start")
        end = citation.get("line_end")
        claim = citation.get("claim")
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
            or not isinstance(claim, str)
            or not claim.strip()
        ):
            raise ValueError("component evidence repair returned a malformed citation")
        source_path = (root / file_id).resolve()
        if root not in source_path.parents or not source_path.is_file():
            raise ValueError(f"component evidence citation is outside repository: {file_id}")
        line_count = len(source_path.read_text(encoding="utf-8").splitlines())
        if end > line_count:
            raise ValueError(f"component evidence citation exceeds the end of {file_id}")

    effective = deepcopy(component)
    effective["evidence"] = replacement
    draft = normalize_component_draft(
        effective,
        component_id=str(component.get("component_id") or "component"),
        origin_strategy=str(component.get("origin_strategy") or "repair"),
    )
    errors = validate_component_draft(draft)
    if errors:
        raise ValueError(f"repaired component evidence violates component schema: {errors}")
    evidence_files = {
        item.get("file_id") for item in replacement if isinstance(item, dict)
    }
    consumers = component.get("protocol_contract", {}).get("consumers", [])
    missing = sorted({
        item.get("file_id")
        for item in consumers
        if isinstance(item, dict) and item.get("file_id") not in evidence_files
    })
    if missing:
        raise ValueError(f"repaired component still lacks consumer evidence: {missing}")


def repair_component_with_agent(
    agent_runner: Any,
    repo_root: Path,
    component: dict[str, Any],
    repair_request: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Run one constrained repair attempt and mechanically validate its scope."""
    target = repair_request.get("repair_target")
    if target not in REPAIR_TARGETS:
        raise ValueError(f"unsupported repair target: {target!r}")
    if component.get("status") != "draft_ready":
        raise ValueError("repair requires a draft_ready component")
    output_dir.mkdir(parents=True, exist_ok=True)
    component_workspace = output_dir / "component_workspace"
    component_workspace.mkdir(exist_ok=True)
    library = component.get("library", {})
    content = library.get("content") if isinstance(library, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("repair requires a non-empty component artifact")
    (component_workspace / "common.py").write_text(content, encoding="utf-8")
    _write_json(component_workspace / "component.json", _component_brief(component))
    _write_json(component_workspace / "repair_request.json", repair_request)
    previous_review = repair_request.get("previous_review")
    if isinstance(previous_review, dict):
        _write_json(component_workspace / "review.json", previous_review)

    result = agent_runner.run_workspace_agent(
        workspace_root=repo_root,
        task=_repair_prompt(repair_request),
        output_dir=output_dir,
        task_label=f"component-repair-{target}",
        agent_role="repair",
        component_workspace=component_workspace,
    )
    if result.get("repair_target") != target:
        raise ValueError("repair agent changed the requested target")
    if result.get("status") == "not_repairable":
        _write_json(output_dir / "repair.json", result)
        return result
    if result.get("status") != "repaired":
        raise ValueError("repair agent returned an invalid status")

    if target == "protocol_contract":
        replacement = result.get("protocol_contract")
        if not isinstance(replacement, dict):
            raise ValueError("protocol repair returned no replacement contract")
        allowed = set(repair_request.get("allowed_protocol_fields", []))
        original = component.get("protocol_contract")
        if not isinstance(original, dict) or not allowed:
            raise ValueError("protocol repair request has no original contract or allowed fields")
        if not allowed <= set(original):
            raise ValueError("protocol repair request names an unknown field")
        for field in set(original) - allowed:
            if replacement.get(field) != original[field]:
                raise ValueError(f"protocol repair changed disallowed field: {field}")
        _validate_protocol_contract_shape(
            replacement,
            repo_root,
            component.get("entrypoints", []),
            label="repaired protocol_contract",
        )
        evidence_files = {
            item.get("file_id")
            for item in component.get("evidence", [])
            if isinstance(item, dict)
        }
        missing_consumer_evidence = sorted({
            item.get("file_id")
            for item in replacement.get("consumers", [])
            if isinstance(item, dict) and item.get("file_id") not in evidence_files
        })
        if missing_consumer_evidence:
            raise ValueError(
                "repaired protocol_contract has consumers without component evidence: "
                f"{missing_consumer_evidence}"
            )
    elif target == "review_manifest":
        if not isinstance(previous_review, dict) or not isinstance(result.get("review"), dict):
            raise ValueError("review repair requires original and replacement reviews")
        _validate_review_repair(
            result["review"], previous_review, component, repo_root, repair_request
        )
    elif target == "component_evidence":
        required = repair_request.get("required_evidence_files")
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(item, str) or not item for item in required)
        ):
            raise ValueError("component evidence repair requires non-empty required_evidence_files")
        _validate_component_evidence_repair(
            result.get("evidence"),
            component,
            repo_root,
            required_files=set(required),
            max_additions=int(repair_request.get("max_evidence_additions", len(required))),
        )
    else:
        repaired_library = result.get("library")
        repaired_content = repaired_library.get("content") if isinstance(repaired_library, dict) else None
        if not isinstance(repaired_content, str):
            raise ValueError("artifact repair returned no Python source")
        _validate_artifact_repair(
            repaired_content,
            component,
            max_changed_lines=int(repair_request.get("max_changed_lines", 20)),
        )
    _write_json(output_dir / "repair.json", result)
    return result
