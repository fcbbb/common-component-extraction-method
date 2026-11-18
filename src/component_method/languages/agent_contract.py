"""Agent-facing JSON contracts shared by prompts and validators.

Prompts render these schemas and the pipeline's validators import the same
constants.  Before this module the review prompt described its output mainly in
prose while the validator demanded exact keys, so an agent could follow the
prompt literally and still have its submission rejected.  Any agent-visible
field, status or enumeration must be defined here and nowhere else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

EXTRACTION_STATUSES = ("ready", "no_component", "uncertain")
COMPONENT_STATUSES = ("draft_ready", "not_extractable")
COMPONENT_TYPES = (
    "existing_reused_asset",
    "cooperating_units",
    "repeated_implementation",
)
COMPONENT_CONFIDENCE = ("high", "medium", "low")
ARTIFACT_FILE_ROLES = ("header", "source", "smoke")
REVIEW_STATUSES = ("confirmed", "rejected", "uncertain")
ARTIFACT_REVIEW_STATUSES = ("faithful", "invalid", "uncertain")
SMOKE_TEST_STATUSES = ("ready", "no_cases", "not_run")
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
PROTOCOL_CONTRACT_REVIEW_STATUSES = (
    "confirmed",
    "confirmed_with_warnings",
    "needs_revision",
    "rejected",
)
PROTOCOL_CONTRACT_ISSUE_STATUSES = (
    "overstated",
    "unsupported",
    "incomplete",
    "inaccurate",
)
PROTOCOL_CONTRACT_ISSUE_SEVERITIES = ("blocking", "warning")
REVIEW_MEMBER_FIELDS = ("file_id", "unit_key", "unit_id", "line_start", "line_end", "note")
# Smoke case ids are used as directory names under the case output root.
SMOKE_CASE_ID_PATTERN = r"[A-Za-z0-9_-]+"

# Keys every extracted component must carry.  ``run_extraction`` uses this for
# the language-aware output contract so the check cannot drift from the prompt.
EXTRACTION_COMPONENT_FIELDS = (
    "component_id",
    "status",
    "name",
    "summary",
    "type",
    "confidence",
    "members",
    "evidence",
    "artifact",
    "protocol_contract",
)


def extraction_output_schema(backend) -> dict[str, Any]:
    """The extraction manifest shape, identical for prompt and validator."""
    return {
        "schema": "component-drafts-v2",
        "status": "ready|no_component|uncertain",
        "reason": "",
        "components": [{
            "component_id": "stable-id",
            "status": "draft_ready|not_extractable",
            "name": "",
            "summary": "",
            "type": "existing_reused_asset|cooperating_units|repeated_implementation",
            "confidence": "high|medium|low",
            "members": [{
                "file_id": "repository-relative/path",
                "unit_key": "copy the source unit key from the packet",
                "unit_id": "same value as unit_key",
                "language": backend.language_id,
                "backend_id": backend.backend_id,
            }],
            "evidence": [{
                "file_id": "repository-relative/path",
                "line_start": 1,
                "line_end": 2,
                "claim": "",
            }],
            "artifact": {
                "schema": "component-artifact-v2",
                "language": backend.language_id,
                "backend_id": backend.backend_id,
                "files": [{
                    "path": "include/... | src/... | smoke/...",
                    "role": "header|source|smoke",
                }],
                "entrypoints": [{
                    "kind": "language unit kind, e.g. function or class",
                    "qualified_name": "declared symbol including its namespace/class",
                    "signature": "exact source signature",
                    "purpose": "",
                }],
                "runtime": {},
            },
            "protocol_contract": {
                field: "source-grounded value" for field in PROTOCOL_CONTRACT_FIELDS
            },
        }],
        "workspace_audit": {"checked_files": [], "gaps": []},
    }


def review_output_schema(backend) -> dict[str, Any]:
    """The review manifest shape, identical for prompt and validator."""
    return {
        "status": "confirmed|rejected|uncertain",
        "reason": "reusable-value decision grounded in source",
        "confirmed_members": [{
            "file_id": "repository-relative/path",
            "unit_key": "copy exactly from component.members[].unit_key",
            "unit_id": "same value as unit_key",
            "line_start": 1,
            "line_end": 1,
            "note": "why this member stays inside the proposed boundary",
        }],
        "evidence": [{
            "file_id": "repository-relative/path",
            "line_start": 1,
            "line_end": 2,
            "claim": "",
        }],
        "artifact_review": {
            "status": "faithful|invalid|uncertain",
            "reason": "",
            "reviewed_files": ["include/...", "src/..."],
            "reviewed_sources": [{
                "file_id": "repository-relative/path",
                "line_start": 1,
                "line_end": 2,
                "note": "",
            }],
            "notes": "",
        },
        "protocol_contract_review": {
            "schema_version": 2,
            "status": "confirmed|confirmed_with_warnings|needs_revision|rejected",
            "reason": "",
            "reviewed_fields": list(PROTOCOL_CONTRACT_FIELDS),
            "confirmed_fields": list(PROTOCOL_CONTRACT_FIELDS),
            "field_issues": [{
                "field": "extension_trigger",
                "status": "overstated|unsupported|incomplete|inaccurate",
                "severity": "blocking|warning",
                "issue": "what the source does not support or what is missing",
                "evidence": [{
                    "file_id": "repository-relative/path",
                    "line_start": 1,
                    "line_end": 2,
                    "claim": "source fact supporting this issue",
                }],
            }],
            "field_revisions": {},
        },
        "smoke_test": {
            "status": "ready|no_cases|not_run",
            "reason": "",
            "cases": [{
                "schema": "smoke-case-v2",
                "case_id": "case-1 (unique, matching " + SMOKE_CASE_ID_PATTERN + ")",
                "entrypoint_id": "declared entrypoint id",
                "files": [{"path": "smoke/case-1.cpp", "role": "smoke"}],
                "sources": [{
                    "file_id": "repository-relative/path",
                    "line_start": 1,
                    "line_end": 2,
                    "role": "interface_contract",
                }],
                "expected_paths": [{"entrypoint_id": "declared entrypoint id"}],
                "metadata": {
                    "language": backend.language_id,
                    "backend_id": backend.backend_id,
                },
            }],
        },
        "validation_dependencies": {
            "complete": True,
            "files": ["repository-relative/path"],
            "search_scopes": ["."],
        },
    }


def _proposed_members(component: Any) -> dict[str, set[str]]:
    """Unit keys the extraction proposed, grouped by source file."""
    if not isinstance(component, dict):
        return {}
    record = (
        component.get("component_draft")
        or component.get("agent_extraction")
        or component.get("extraction")
        or component
    )
    if not isinstance(record, dict):
        return {}
    allowed: dict[str, set[str]] = {}
    for item in record.get("members", []) or []:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        key = item.get("unit_key") or item.get("unit_id")
        if isinstance(file_id, str) and isinstance(key, str) and key:
            allowed.setdefault(file_id, set()).add(key)
    return allowed


def source_units(backend, repository_root: Path, file_id: str) -> list[Any]:
    path = repository_root / file_id
    try:
        if not path.is_file():
            return []
        return backend.extract_units(file_id, path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return []


def _record_of(container: Any) -> Any:
    if not isinstance(container, dict):
        return container
    return (
        container.get("component_draft")
        or container.get("agent_extraction")
        or container.get("extraction")
        or container
    )


def annotate_component_members(component: Any, backend, repository_root: Path) -> Any:
    """Copy the component with member names and spans resolved from source.

    ``component.members`` carries opaque unit keys.  A reviewer asked to copy
    those keys cannot tell which declaration each key denotes, so the review
    prompt shows the resolved name, qualified name and line range next to the
    key.  The annotation is display-only: normalization and validators still
    read the canonical members of the original component.
    """
    from copy import deepcopy

    record = _record_of(component)
    if not isinstance(record, dict) or not isinstance(record.get("members"), list):
        return component
    annotated = deepcopy(component)
    target = _record_of(annotated)
    cache: dict[str, list[Any]] = {}
    for row in target.get("members", []):
        if not isinstance(row, dict):
            continue
        file_id = row.get("file_id")
        key = row.get("unit_key") or row.get("unit_id")
        if not isinstance(file_id, str) or not isinstance(key, str) or not key:
            continue
        units = cache.get(file_id)
        if units is None:
            units = source_units(backend, repository_root, file_id)
            cache[file_id] = units
        unit = next((item for item in units if item.unit_key == key), None)
        if unit is None:
            unit = next((item for item in units if item.unit_key.startswith(key)), None)
        if unit is not None:
            row.setdefault("name", unit.display_name)
            row.setdefault("qualified_name", unit.qualified_name)
            row.setdefault("line_start", unit.span.start_line)
            row.setdefault("line_end", unit.span.end_line)
    return annotated


def _member_keys(member: dict, candidates: set[str], units: list[Any]) -> set[str] | None:
    """Resolve one review citation onto the proposed unit keys.

    The canonical form copies ``unit_key``.  Reviewers may also cite the exact
    ``member`` name and source line range they see in ``component.members``;
    those citations are grounded against the parsed source units.
    """
    for field in ("unit_key", "unit_id"):
        value = member.get(field)
        if not isinstance(value, str) or not value:
            continue
        if value in candidates:
            return {value}
        matches = {candidate for candidate in candidates if candidate.startswith(value)}
        if matches:
            return matches

    name = next(
        (member.get(field) for field in ("member", "name", "qualified_name", "symbol")
         if isinstance(member.get(field), str) and member[field].strip()),
        None,
    )
    by_name: set[str] = set()
    if name:
        name = name.strip()
        by_name = {
            unit.unit_key for unit in units
            if unit.unit_key in candidates and (
                unit.qualified_name == name
                or unit.display_name == name
                or unit.qualified_name.endswith("::" + name)
                or unit.qualified_name.endswith("." + name)
            )
        }
    if len(by_name) == 1:
        return by_name

    start, end = member.get("line_start"), member.get("line_end")
    if type(start) is int and type(end) is int and start >= 1 and end >= start:
        contained = {
            unit.unit_key for unit in units
            if unit.unit_key in candidates
            and start <= unit.span.start_line and unit.span.end_line <= end
        }
        if contained:
            return contained
        overlapping = {
            unit.unit_key for unit in units
            if unit.unit_key in candidates
            and unit.span.start_line <= end and start <= unit.span.end_line
        }
        if overlapping:
            return overlapping
    return by_name or None


def _declared_entrypoint_ids(component: Any) -> set[str]:
    record = _record_of(component)
    if not isinstance(record, dict):
        return set()
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        return set()
    names: set[str] = set()
    for entry in artifact.get("entrypoints") or []:
        if not isinstance(entry, dict):
            continue
        for field in ("entrypoint_id", "id", "qualified_name", "name"):
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    return names


def _normalize_smoke_cases(review: dict[str, Any], component: Any) -> dict[str, Any]:
    """Canonicalize ``smoke_test.cases[].expected_paths`` to ``entrypoint_id``.

    The contract is one object ``{"entrypoint_id": "<declared id>"}`` per path.
    Reviewers occasionally emit ``{"<declared id>": "<expected behavior>"}``
    instead: same intent, one key whose key is the entrypoint.  Ground that
    shape here, before the validator, and leave everything else untouched so
    the strict shape check still rejects entries that name no declared
    entrypoint.
    """
    plan = review.get("smoke_test")
    if not isinstance(plan, dict) or not isinstance(plan.get("cases"), list):
        return review
    declared = _declared_entrypoint_ids(component)
    if not declared:
        return review
    changed = False
    cases = []
    for case in plan["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("expected_paths"), list):
            cases.append(case)
            continue
        paths = []
        for item in case["expected_paths"]:
            if isinstance(item, dict) and "entrypoint_id" in item:
                if set(item) != {"entrypoint_id"}:
                    item = {"entrypoint_id": item["entrypoint_id"]}
                    changed = True
            elif isinstance(item, dict) and len(item) == 1:
                (key, _description), = item.items()
                if key in declared:
                    item = {"entrypoint_id": key}
                    changed = True
            elif isinstance(item, str) and item.strip() in declared:
                item = {"entrypoint_id": item.strip()}
                changed = True
            paths.append(item)
        cases.append({**case, "expected_paths": paths} if paths != case["expected_paths"] else case)
    if not changed:
        return review
    return {**review, "smoke_test": {**plan, "cases": cases}}


def normalize_review_result(
    review: Any,
    *,
    component: Any,
    backend,
    repository_root: Path,
) -> Any:
    """Rewrite review member citations into the canonical ``unit_key`` form.

    Runs at the pipeline boundary, before any validator sees the review, so the
    documented prompt shapes (copy ``unit_key`` or cite ``member`` plus a line
    range) are the only shapes validators ever handle.  Unresolvable citations
    are left untouched for the boundary check to reject explicitly.  Smoke
    ``expected_paths`` are canonicalized here as well.
    """
    if not isinstance(review, dict):
        return review
    result = review
    members = review.get("confirmed_members")
    if isinstance(members, list):
        result = _normalize_review_members(result, component, backend, repository_root)
    return _normalize_smoke_cases(result, component)


def _normalize_review_members(
    review: dict[str, Any],
    component: Any,
    backend,
    repository_root: Path,
) -> dict[str, Any]:
    members = review["confirmed_members"]
    allowed = _proposed_members(component)
    if not allowed:
        return review
    units_cache: dict[str, list[Any]] = {}
    normalized = []
    changed = False
    for member in members:
        if not isinstance(member, dict):
            normalized.append(member)
            continue
        file_id = member.get("file_id")
        candidates = allowed.get(file_id) if isinstance(file_id, str) else None
        if not candidates:
            normalized.append(member)
            continue
        if file_id not in units_cache:
            units_cache[file_id] = source_units(backend, repository_root, file_id)
        keys = _member_keys(member, candidates, units_cache[file_id])
        if not keys:
            normalized.append(member)
            continue
        for key in sorted(keys):
            normalized.append({**member, "unit_key": key, "unit_id": key})
        changed = changed or keys != {member.get("unit_key")}
    if not changed:
        return review
    return {**review, "confirmed_members": normalized}