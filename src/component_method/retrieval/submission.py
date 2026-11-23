#!/usr/bin/env python3
"""Validate a retrieval agent's file-based component selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DELIVERY_MODES = {"direct_reuse", "reference_pattern"}
RELATIONS = {"direct", "protocol", "none"}
ASSESSMENT_DECISIONS = {"shortlist", "reject"}
SHORTLIST_REVIEW_DECISIONS = {"select", "omit"}
COVERAGE_VERDICTS = {"confirmed", "refuted", "duplicate"}
CHANGE_KINDS = {
    "representation",
    "validation",
    "dispatch",
    "serialization",
    "identity",
    "persistence",
    "state",
    "lifecycle",
    "construction",
    "interface",
    "behavior",
    "other",
}
COVERAGE_SIGNALS = {
    "capability",
    "semantic_domain",
    "extension_trigger",
    "consumers",
    "reuse_interface",
    "boundary",
}
DIRECT_MATCH_SIGNALS = {"capability", "semantic_domain", "reuse_interface"}

# Methodology libraries carry Markdown components instead of executable code.
# Their selection contract is a path list: choose bundle IDs and stop.  Reasons,
# usage notes, boundaries and evidence belong in the component README, which the
# Task Agent reads directly.  Coverage matrices, audits and protocol contracts do
# not apply.
METHODOLOGY_SCHEMA = "methodology-1"
METHODOLOGY_SELECTION_SCHEMA = "methodology-paths-1"
METHODOLOGY_KIND = "methodology"
METHODOLOGY_MAX_SELECTED = 2
# The legacy schema is still accepted so existing run artifacts remain readable.
METHODOLOGY_MIN_TEXT = 20
METHODOLOGY_MIN_OMISSION = 10

# Single source for the concreteness thresholds.  ``concreteness_minimums_text``
# renders these numbers into the retrieval prompt, so the instruction the agent
# reads and the check the validator applies cannot drift apart.
CONCRETENESS_MINIMUMS = {
    "change_model.changed_entities": 3,
    "change_model.introduced_or_changed_variants": 3,
    "change_model.change_kinds": 3,
    "change_model.propagation_risks": 10,
    "task_baseline.explicit_information": 10,
    "task_baseline.obvious_scope": 10,
    "component_coverage.direct_assessment.matched_entities": 3,
    "component_coverage.direct_assessment.catalog_signals": 3,
    "component_coverage.direct_assessment.reason": 25,
    "component_coverage.direct_assessment.probe": 20,
    "component_coverage.changed_entities": 3,
    "component_coverage.catalog_signals": 3,
    "component_coverage.path": 25,
    "component_assessments.reason": 15,
    "shortlist_reviews.marginal_value": 25,
    "shortlist_reviews.boundary": 15,
    "selected.task_overlap": 15,
    "selected.boundary": 15,
    "selected.usage": 20,
    "selected.incremental_contribution": 25,
    "propagation_checks.carrier": 15,
    "propagation_checks.changed_variants": 3,
    "propagation_checks.bundle_ids": 3,
    "propagation_checks.symbols": 3,
    "propagation_checks.argument_positions": 3,
    "propagation_checks.invariant": 25,
}


def concreteness_minimums_text() -> str:
    """Render the validator's concreteness thresholds for the agent prompt."""
    grouped: dict[int, list[str]] = {}
    for field, minimum in CONCRETENESS_MINIMUMS.items():
        grouped.setdefault(minimum, []).append(field)
    sentences = [
        f"{', '.join(grouped[minimum])} need at least {minimum} characters"
        for minimum in sorted(grouped)
    ]
    return "Concreteness minimums enforced by the validator: " + "; ".join(sentences) + "."


def methodology_minimums_text() -> str:
    """Render the methodology validator's limits for the retrieval prompt."""
    return (
        "Validator limits: select at most "
        f"{METHODOLOGY_MAX_SELECTED} component IDs. The file contains only "
        "schema_version, task_id and selected_bundle_ids."
    )


def _inside(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError(f"evidence path must be relative: {relative!r}")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"evidence path escapes component library: {relative}") from exc
    if not target.is_file():
        raise ValueError(f"evidence file does not exist: {relative}")
    return target


def _concrete_text(item: dict[str, Any], field: str, index: int, minimum: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"selected[{index}].{field} must be concrete")
    return value.strip()


def _concrete_string_list(
    value: Any,
    field: str,
    *,
    minimum_length: int,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{field} must be {qualifier}")
    normalized = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or len(item.strip()) < minimum_length:
            raise ValueError(f"{field}[{index}] must be concrete")
        item = item.strip()
        if item in normalized:
            raise ValueError(f"{field} must not repeat values")
        normalized.append(item)
    return normalized


def is_methodology_manifest(manifest: dict[str, Any]) -> bool:
    """Whether a library uses the Markdown methodology contract."""
    return (
        manifest.get("kind") == METHODOLOGY_KIND
        or manifest.get("schema_version") == METHODOLOGY_SCHEMA
    )


def _checked_citation(
    library: Path, citation: Any, *, label: str
) -> dict[str, Any]:
    if not isinstance(citation, dict):
        raise ValueError(f"{label} must be an object")
    relative = citation.get("path")
    start = citation.get("line_start")
    end = citation.get("line_end")
    excerpt = citation.get("excerpt")
    if not isinstance(relative, str):
        raise ValueError(f"{label}.path is missing")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        raise ValueError(f"{label} line range is invalid")
    source = _inside(library, relative)
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    if end > len(lines):
        raise ValueError(f"{label} line range exceeds {relative}")
    cited = "\n".join(lines[start - 1 : end])
    if not isinstance(excerpt, str) or not excerpt.strip() or excerpt.strip() not in cited:
        raise ValueError(f"{label} excerpt is not exact in {relative}")
    return {
        "path": relative,
        "line_start": start,
        "line_end": end,
        "excerpt": excerpt.strip(),
    }


def validate_methodology_selection(
    library: Path,
    selection_path: Path,
    *,
    expected_task_id: str | None = None,
) -> dict[str, Any]:
    """Validate a path-only selection over Markdown methodology components.

    The current schema names bundle IDs only.  The Task Agent reads the selected
    READMEs directly, so the retrieval step never produces a task-specific
    summary.  The legacy reason/usage/evidence schema remains readable.
    Coverage matrices and protocol contracts belong to code components and are
    intentionally absent here.
    """
    library = library.resolve()
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    components = [
        item for item in manifest.get("components", []) if isinstance(item, dict)
    ]
    if not components:
        raise ValueError("component library manifest has no components")
    valid_ids = {item.get("bundle_id") for item in components}
    if None in valid_ids or len(valid_ids) != len(components):
        raise ValueError("component library manifest has invalid or repeated bundle IDs")
    component_dir_by_id = {
        item["bundle_id"]: Path(item["readme"]).parent.as_posix()
        for item in components
        if isinstance(item.get("readme"), str)
    }

    value = json.loads(selection_path.read_text(encoding="utf-8"))
    schema_version = value.get("schema_version")
    supported = {METHODOLOGY_SELECTION_SCHEMA, METHODOLOGY_SCHEMA}
    if schema_version not in supported:
        raise ValueError(
            f"schema_version must be {METHODOLOGY_SELECTION_SCHEMA!r} "
            f"(legacy {METHODOLOGY_SCHEMA!r} is also accepted)"
        )
    task_id = value.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    if expected_task_id is not None and task_id != expected_task_id:
        raise ValueError(f"task_id must be {expected_task_id!r}")

    if schema_version == METHODOLOGY_SELECTION_SCHEMA:
        unexpected = set(value) - {"schema_version", "task_id", "selected_bundle_ids"}
        if unexpected:
            raise ValueError(
                "selection.json must contain only schema_version, task_id and "
                f"selected_bundle_ids; unexpected fields: {sorted(unexpected)}"
            )
        selected_ids = value.get("selected_bundle_ids")
        if not isinstance(selected_ids, list) or len(selected_ids) > METHODOLOGY_MAX_SELECTED:
            raise ValueError(
                "selected_bundle_ids must be a list of at most "
                f"{METHODOLOGY_MAX_SELECTED} component IDs"
            )
        normalized_ids: list[str] = []
        for index, bundle_id in enumerate(selected_ids):
            if not isinstance(bundle_id, str) or bundle_id not in valid_ids:
                raise ValueError(
                    f"selected_bundle_ids[{index}] has unknown bundle_id: {bundle_id!r}"
                )
            if bundle_id in normalized_ids:
                raise ValueError(f"selected_bundle_ids repeats bundle_id: {bundle_id}")
            normalized_ids.append(bundle_id)
        return {
            "schema_version": METHODOLOGY_SELECTION_SCHEMA,
            "task_id": task_id,
            "selected_bundle_ids": normalized_ids,
        }

    selected = value.get("selected")
    if not isinstance(selected, list) or len(selected) > METHODOLOGY_MAX_SELECTED:
        raise ValueError(
            f"selected must be a list of at most {METHODOLOGY_MAX_SELECTED} components"
        )
    normalized_selected = []
    seen: set[str] = set()
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            raise ValueError(f"selected[{index}] must be an object")
        bundle_id = item.get("bundle_id")
        if bundle_id not in valid_ids:
            raise ValueError(f"selected[{index}] has unknown bundle_id: {bundle_id!r}")
        if bundle_id in seen:
            raise ValueError(f"selected repeats bundle_id: {bundle_id}")
        seen.add(bundle_id)
        reason = _concrete_text(item, "reason", index, METHODOLOGY_MIN_TEXT)
        usage = _concrete_text(item, "usage", index, METHODOLOGY_MIN_TEXT)
        boundary = item.get("boundary")
        if boundary is not None and (
            not isinstance(boundary, str) or len(boundary.strip()) < METHODOLOGY_MIN_TEXT
        ):
            raise ValueError(f"selected[{index}].boundary must be concrete when present")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"selected[{index}].evidence must not be empty")
        checked_evidence = [
            _checked_citation(library, citation, label=f"selected[{index}].evidence[{position}]")
            for position, citation in enumerate(evidence)
        ]
        component_dir = component_dir_by_id.get(bundle_id)
        for citation in checked_evidence:
            if component_dir and not citation["path"].startswith(component_dir + "/"):
                raise ValueError(
                    f"selected[{index}] evidence must cite {component_dir}/: "
                    f"{citation['path']}"
                )
        normalized_selected.append({
            "bundle_id": bundle_id,
            "reason": reason,
            "usage": usage,
            "boundary": boundary.strip() if isinstance(boundary, str) else "",
            "evidence": checked_evidence,
        })

    omitted = value.get("omitted", [])
    if not isinstance(omitted, list):
        raise ValueError("omitted must be a list when present")
    normalized_omitted = []
    omitted_ids: set[str] = set()
    for index, item in enumerate(omitted):
        if not isinstance(item, dict):
            raise ValueError(f"omitted[{index}] must be an object")
        bundle_id = item.get("bundle_id")
        if bundle_id not in valid_ids:
            raise ValueError(f"omitted[{index}] has unknown bundle_id: {bundle_id!r}")
        if bundle_id in omitted_ids:
            raise ValueError(f"omitted repeats bundle_id: {bundle_id}")
        if bundle_id in seen:
            raise ValueError(f"omitted bundle is also selected: {bundle_id}")
        omitted_ids.add(bundle_id)
        reason = item.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < METHODOLOGY_MIN_OMISSION:
            raise ValueError(f"omitted[{index}].reason must be concrete")
        normalized_omitted.append({"bundle_id": bundle_id, "reason": reason.strip()})

    return {
        "schema_version": METHODOLOGY_SCHEMA,
        "task_id": task_id,
        "selected_bundle_ids": [item["bundle_id"] for item in normalized_selected],
        "selected": normalized_selected,
        "omitted": normalized_omitted,
    }


def _normalize_change_model(
    value: Any, *, require_introduced_variants: bool = False
) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("change_model must be an object")
    changed_entities = _concrete_string_list(
        value.get("changed_entities"),
        "change_model.changed_entities",
        minimum_length=CONCRETENESS_MINIMUMS["change_model.changed_entities"],
    )
    change_kinds = _concrete_string_list(
        value.get("change_kinds"),
        "change_model.change_kinds",
        minimum_length=CONCRETENESS_MINIMUMS["change_model.change_kinds"],
    )
    unknown_kinds = set(change_kinds) - CHANGE_KINDS
    if unknown_kinds:
        raise ValueError(f"change_model.change_kinds contains unknown values: {sorted(unknown_kinds)}")
    introduced_variants = _concrete_string_list(
        value.get("introduced_or_changed_variants", []),
        "change_model.introduced_or_changed_variants",
        minimum_length=CONCRETENESS_MINIMUMS["change_model.introduced_or_changed_variants"],
        allow_empty=True,
    )
    if require_introduced_variants and "representation" in change_kinds and not introduced_variants:
        raise ValueError(
            "representation changes require change_model.introduced_or_changed_variants"
        )
    propagation_risks = _concrete_string_list(
        value.get("propagation_risks"),
        "change_model.propagation_risks",
        minimum_length=CONCRETENESS_MINIMUMS["change_model.propagation_risks"],
        allow_empty=True,
    )
    return {
        "changed_entities": changed_entities,
        "introduced_or_changed_variants": introduced_variants,
        "change_kinds": change_kinds,
        "propagation_risks": propagation_risks,
    }


def validate_coverage(
    library: Path,
    coverage_path: Path,
    *,
    expected_task_id: str | None = None,
) -> dict[str, Any]:
    """Validate the pre-selection semantic-entity to protocol-boundary pass."""
    library = library.resolve()
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    components = manifest.get("components", [])
    valid_ids = {
        item["bundle_id"]
        for item in components
        if isinstance(item, dict) and isinstance(item.get("bundle_id"), str)
    }
    if not valid_ids or len(valid_ids) != len(components):
        raise ValueError("component library manifest has invalid or repeated bundle IDs")

    available_signals: dict[str, set[str]] = {}
    entrypoints_by_id: dict[str, set[str]] = {}
    for component in components:
        signals: set[str] = set()
        entrypoints: set[str] = set()
        audit_relative = component.get("audit_file")
        if isinstance(audit_relative, str):
            audit = json.loads(_inside(library, audit_relative).read_text(encoding="utf-8"))
            entrypoints = {
                entry["name"]
                for entry in audit.get("entrypoints", [])
                if isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
                and entry["name"].strip()
            }
            if audit.get("capability") or audit.get("summary"):
                signals.add("capability")
            contract = audit.get("protocol_contract")
            if isinstance(contract, dict):
                for signal in COVERAGE_SIGNALS:
                    if contract.get(signal):
                        signals.add(signal)
        available_signals[component["bundle_id"]] = signals
        entrypoints_by_id[component["bundle_id"]] = entrypoints

    value = json.loads(coverage_path.read_text(encoding="utf-8"))
    schema_version = value.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError("coverage schema_version must be 1 or 2")
    task_id = value.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("coverage task_id must be a non-empty string")
    if expected_task_id is not None and task_id != expected_task_id:
        raise ValueError(f"coverage task_id must be {expected_task_id!r}")
    change_model = _normalize_change_model(
        value.get("change_model"), require_introduced_variants=True
    )
    changed_entity_set = set(change_model["changed_entities"]) | set(
        change_model["introduced_or_changed_variants"]
    )

    entries = value.get("component_coverage")
    if not isinstance(entries, list):
        raise ValueError("component_coverage must be a list")
    seen: set[str] = set()
    normalized_entries = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"component_coverage[{index}] must be an object")
        bundle_id = entry.get("bundle_id")
        if bundle_id not in valid_ids:
            raise ValueError(f"component_coverage[{index}] has unknown bundle_id: {bundle_id!r}")
        if bundle_id in seen:
            raise ValueError(f"component_coverage repeats bundle_id: {bundle_id}")
        seen.add(bundle_id)
        relation = entry.get("relation")
        if relation not in RELATIONS:
            raise ValueError(
                f"component_coverage[{index}].relation must be one of {sorted(RELATIONS)}"
            )
        direct_assessment = None
        if schema_version == 2:
            raw_direct = entry.get("direct_assessment")
            if not isinstance(raw_direct, dict):
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment must be an object"
                )
            verdict = raw_direct.get("verdict")
            if verdict not in {"match", "no_match"}:
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment.verdict must be "
                    "match or no_match"
                )
            matched_entities = _concrete_string_list(
                raw_direct.get("matched_entities"),
                f"component_coverage[{index}].direct_assessment.matched_entities",
                minimum_length=CONCRETENESS_MINIMUMS[
                    "component_coverage.direct_assessment.matched_entities"
                ],
                allow_empty=True,
            )
            unknown_direct_entities = set(matched_entities) - changed_entity_set
            if unknown_direct_entities:
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment references unknown "
                    f"entities: {sorted(unknown_direct_entities)}"
                )
            direct_signals = _concrete_string_list(
                raw_direct.get("catalog_signals"),
                f"component_coverage[{index}].direct_assessment.catalog_signals",
                minimum_length=CONCRETENESS_MINIMUMS[
                    "component_coverage.direct_assessment.catalog_signals"
                ],
                allow_empty=True,
            )
            unknown_direct_signals = set(direct_signals) - DIRECT_MATCH_SIGNALS
            if unknown_direct_signals:
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment has invalid direct "
                    f"signals: {sorted(unknown_direct_signals)}"
                )
            unavailable_direct = set(direct_signals) - available_signals[bundle_id]
            if unavailable_direct:
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment cites unavailable "
                    f"signals: {sorted(unavailable_direct)}"
                )
            direct_reason = raw_direct.get("reason")
            if (
                not isinstance(direct_reason, str)
                or len(direct_reason.strip())
                < CONCRETENESS_MINIMUMS["component_coverage.direct_assessment.reason"]
            ):
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment.reason must be concrete"
                )
            probe = raw_direct.get("probe")
            entrypoint = raw_direct.get("entrypoint")
            can_invoke = raw_direct.get("can_invoke_with_variant")
            if not isinstance(can_invoke, bool):
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment."
                    "can_invoke_with_variant must be boolean"
                )
            if entrypoint not in entrypoints_by_id[bundle_id]:
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment.entrypoint must name "
                    f"a published entrypoint for {bundle_id}"
                )
            if (
                not isinstance(probe, str)
                or len(probe.strip())
                < CONCRETENESS_MINIMUMS["component_coverage.direct_assessment.probe"]
            ):
                raise ValueError(
                    f"component_coverage[{index}].direct_assessment.probe must be concrete"
                )
            if verdict == "match":
                if not can_invoke:
                    raise ValueError(
                        f"component_coverage[{index}] direct match requires invokable variant"
                    )
                if not matched_entities or not direct_signals:
                    raise ValueError(
                        f"component_coverage[{index}] direct match requires entities and signals"
                    )
                if relation != "direct":
                    raise ValueError(
                        f"component_coverage[{index}] direct match requires relation direct"
                    )
            else:
                if can_invoke:
                    raise ValueError(
                        f"component_coverage[{index}] invokable variant requires a direct match"
                    )
                if matched_entities or direct_signals:
                    raise ValueError(
                        f"component_coverage[{index}] no_match requires empty entities and signals"
                    )
                if relation == "direct":
                    raise ValueError(
                        f"component_coverage[{index}] relation direct requires a direct match"
                    )
            direct_assessment = {
                "verdict": verdict,
                "matched_entities": matched_entities,
                "catalog_signals": direct_signals,
                "reason": direct_reason.strip(),
                "entrypoint": entrypoint,
                "probe": probe.strip(),
                "can_invoke_with_variant": can_invoke,
            }
        changed_entities = _concrete_string_list(
            entry.get("changed_entities"),
            f"component_coverage[{index}].changed_entities",
            minimum_length=CONCRETENESS_MINIMUMS["component_coverage.changed_entities"],
            allow_empty=True,
        )
        unknown_entities = set(changed_entities) - changed_entity_set
        if unknown_entities:
            raise ValueError(
                f"component_coverage[{index}] references unknown changed entities: "
                f"{sorted(unknown_entities)}"
            )
        catalog_signals = _concrete_string_list(
            entry.get("catalog_signals"),
            f"component_coverage[{index}].catalog_signals",
            minimum_length=CONCRETENESS_MINIMUMS["component_coverage.catalog_signals"],
            allow_empty=True,
        )
        unknown_signals = set(catalog_signals) - COVERAGE_SIGNALS
        if unknown_signals:
            raise ValueError(
                f"component_coverage[{index}] has unknown catalog signals: "
                f"{sorted(unknown_signals)}"
            )
        unavailable = set(catalog_signals) - available_signals[bundle_id]
        if unavailable:
            raise ValueError(
                f"component_coverage[{index}] cites unavailable catalog signals: "
                f"{sorted(unavailable)}"
            )
        path = entry.get("path")
        if (
            not isinstance(path, str)
            or len(path.strip()) < CONCRETENESS_MINIMUMS["component_coverage.path"]
        ):
            raise ValueError(f"component_coverage[{index}].path must be concrete")
        if relation == "none" and (changed_entities or catalog_signals):
            raise ValueError(
                f"component_coverage[{index}] relation none must have empty entities and signals"
            )
        if relation != "none" and (not changed_entities or not catalog_signals):
            raise ValueError(
                f"component_coverage[{index}] relation {relation} requires entities and signals"
            )
        normalized_entry = {
            "bundle_id": bundle_id,
            "relation": relation,
            "changed_entities": changed_entities,
            "catalog_signals": catalog_signals,
            "path": path.strip(),
        }
        if direct_assessment is not None:
            normalized_entry["direct_assessment"] = direct_assessment
        normalized_entries.append(normalized_entry)
    if seen != valid_ids or len(entries) != len(valid_ids):
        missing = sorted(valid_ids - seen)
        raise ValueError(
            "component_coverage must cover every manifest component exactly once; "
            f"missing={missing}"
        )
    covered_count = sum(entry["relation"] != "none" for entry in normalized_entries)
    if covered_count > min(8, len(valid_ids)):
        raise ValueError("component_coverage may contain at most eight non-none relations")
    return {
        "schema_version": schema_version,
        "task_id": task_id,
        "change_model": change_model,
        "component_coverage": normalized_entries,
        "covered_bundle_ids": [
            entry["bundle_id"] for entry in normalized_entries if entry["relation"] != "none"
        ],
    }


def validate_selection(
    library: Path,
    selection_path: Path,
    *,
    expected_task_id: str | None = None,
    coverage_path: Path | None = None,
) -> dict[str, Any]:
    """Validate selected IDs, marginal-value statements, and exact evidence."""
    library = library.resolve()
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    if is_methodology_manifest(manifest):
        return validate_methodology_selection(
            library, selection_path, expected_task_id=expected_task_id
        )
    components = manifest.get("components", [])
    if not isinstance(components, list) or not components:
        raise ValueError("component library manifest has no components")
    valid_ids = {
        item["bundle_id"]
        for item in components
        if isinstance(item, dict) and isinstance(item.get("bundle_id"), str)
    }
    if len(valid_ids) != len(components):
        raise ValueError("component library manifest has invalid or repeated bundle IDs")

    source_digest_by_id: dict[str, str] = {}
    entrypoint_family_by_id: dict[str, tuple[str, ...]] = {}
    protocol_status_by_id: dict[str, str] = {}
    for item in components:
        relative = item.get("library") if isinstance(item, dict) else None
        if isinstance(relative, str):
            source = _inside(library, relative)
            source_digest_by_id[item["bundle_id"]] = hashlib.sha256(source.read_bytes()).hexdigest()
        audit_relative = item.get("audit_file") if isinstance(item, dict) else None
        if isinstance(audit_relative, str):
            audit = json.loads(_inside(library, audit_relative).read_text(encoding="utf-8"))
            if isinstance(audit.get("protocol_status"), str):
                protocol_status_by_id[item["bundle_id"]] = audit["protocol_status"]
            entrypoints = tuple(sorted({
                entry["name"]
                for entry in audit.get("entrypoints", [])
                if isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
                and entry["name"].strip()
            }))
            if entrypoints:
                entrypoint_family_by_id[item["bundle_id"]] = entrypoints

    value = json.loads(selection_path.read_text(encoding="utf-8"))
    schema_version = value.get("schema_version")
    if schema_version not in {4, 5, 6, 7, 8, 9}:
        raise ValueError("schema_version must be 4, 5, 6, 7, 8, or 9")
    task_id = value.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    if expected_task_id is not None and task_id != expected_task_id:
        raise ValueError(f"task_id must be {expected_task_id!r}")

    task_baseline = value.get("task_baseline")
    if not isinstance(task_baseline, dict):
        raise ValueError("task_baseline must be an object")
    normalized_explicit = _concrete_string_list(
        task_baseline.get("explicit_information"),
        "task_baseline.explicit_information",
        minimum_length=CONCRETENESS_MINIMUMS["task_baseline.explicit_information"],
    )
    obvious_scope = task_baseline.get("obvious_scope")
    if (
        not isinstance(obvious_scope, str)
        or len(obvious_scope.strip()) < CONCRETENESS_MINIMUMS["task_baseline.obvious_scope"]
    ):
        raise ValueError("task_baseline.obvious_scope must be concrete")

    normalized_change_model = None
    normalized_assessments = None
    normalized_shortlist = None
    normalized_coverage = None
    coverage_digest = None
    normalized_reviews = None
    reviewed_selected_ids: set[str] | None = None
    duplicate_targets: dict[str, str] = {}
    if schema_version in {5, 6, 7, 8, 9}:
        normalized_change_model = _normalize_change_model(value.get("change_model"))
        if schema_version in {6, 7, 8, 9}:
            if coverage_path is None:
                sibling_coverage = selection_path.with_name("coverage.json")
                submitted_coverage = selection_path.parent / "submission" / "coverage.json"
                coverage_path = (
                    sibling_coverage
                    if sibling_coverage.is_file()
                    else submitted_coverage
                )
            normalized_coverage = validate_coverage(
                library,
                coverage_path,
                expected_task_id=expected_task_id,
            )
            if normalized_coverage["change_model"] != normalized_change_model:
                raise ValueError("selection change_model must exactly match coverage.json")
            coverage_digest = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
            if value.get("coverage_sha256") != coverage_digest:
                raise ValueError("coverage_sha256 must match coverage.json")

        assessments = value.get("component_assessments")
        if not isinstance(assessments, list):
            raise ValueError("component_assessments must be a list")
        assessment_ids = []
        normalized_assessments = []
        assessed_shortlist = []
        for index, assessment in enumerate(assessments):
            if not isinstance(assessment, dict):
                raise ValueError(f"component_assessments[{index}] must be an object")
            bundle_id = assessment.get("bundle_id")
            if bundle_id not in valid_ids:
                raise ValueError(
                    f"component_assessments[{index}] has unknown bundle_id: {bundle_id!r}"
                )
            if bundle_id in assessment_ids:
                raise ValueError(f"component_assessments repeats bundle_id: {bundle_id}")
            assessment_ids.append(bundle_id)
            relation = assessment.get("relation")
            if relation not in RELATIONS:
                raise ValueError(
                    f"component_assessments[{index}].relation must be one of {sorted(RELATIONS)}"
                )
            decision = assessment.get("decision")
            if decision not in ASSESSMENT_DECISIONS:
                raise ValueError(
                    f"component_assessments[{index}].decision must be one of "
                    f"{sorted(ASSESSMENT_DECISIONS)}"
                )
            reason = _concrete_text(
                assessment,
                "reason",
                index,
                CONCRETENESS_MINIMUMS["component_assessments.reason"],
            )
            if decision == "shortlist":
                assessed_shortlist.append(bundle_id)
            normalized_assessments.append({
                "bundle_id": bundle_id,
                "relation": relation,
                "decision": decision,
                "reason": reason,
            })
        if set(assessment_ids) != valid_ids or len(assessment_ids) != len(valid_ids):
            missing = sorted(valid_ids - set(assessment_ids))
            raise ValueError(
                "component_assessments must cover every manifest component exactly once; "
                f"missing={missing}"
            )

        shortlist = value.get("shortlisted_bundle_ids")
        shortlist_maximum = min(8, len(valid_ids))
        if not isinstance(shortlist, list) or len(shortlist) > shortlist_maximum:
            raise ValueError(
                f"shortlisted_bundle_ids must contain between 0 and {shortlist_maximum} IDs"
            )
        if any(bundle_id not in valid_ids for bundle_id in shortlist):
            raise ValueError("shortlisted_bundle_ids contains an unknown bundle ID")
        if len(set(shortlist)) != len(shortlist):
            raise ValueError("shortlisted_bundle_ids must not repeat IDs")
        if set(shortlist) != set(assessed_shortlist):
            raise ValueError(
                "shortlisted_bundle_ids must exactly match component_assessments shortlist decisions"
            )
        normalized_shortlist = list(shortlist)
        if schema_version in {6, 7, 8, 9}:
            coverage_relation_by_id = {
                item["bundle_id"]: item["relation"]
                for item in normalized_coverage["component_coverage"]
            }
            for assessment in normalized_assessments:
                bundle_id = assessment["bundle_id"]
                if assessment["relation"] != coverage_relation_by_id[bundle_id]:
                    raise ValueError(
                        f"component_assessments relation must match coverage.json for {bundle_id}"
                    )
                expected_decision = (
                    "shortlist" if coverage_relation_by_id[bundle_id] != "none" else "reject"
                )
                if assessment["decision"] != expected_decision:
                    raise ValueError(
                        f"component_assessments decision must follow coverage.json for {bundle_id}"
                    )
        if schema_version in {7, 8, 9}:
            reviews = value.get("shortlist_reviews")
            if not isinstance(reviews, list):
                raise ValueError("shortlist_reviews must be a list")
            review_ids: list[str] = []
            normalized_reviews = []
            reviewed_selected_ids = set()
            for review_index, review in enumerate(reviews):
                if not isinstance(review, dict):
                    raise ValueError(f"shortlist_reviews[{review_index}] must be an object")
                bundle_id = review.get("bundle_id")
                if bundle_id not in normalized_shortlist:
                    raise ValueError(
                        f"shortlist_reviews[{review_index}] must reference a shortlisted component"
                    )
                if bundle_id in review_ids:
                    raise ValueError(f"shortlist_reviews repeats bundle_id: {bundle_id}")
                review_ids.append(bundle_id)
                decision = review.get("decision")
                if decision not in SHORTLIST_REVIEW_DECISIONS:
                    raise ValueError(
                        f"shortlist_reviews[{review_index}].decision must be one of "
                        f"{sorted(SHORTLIST_REVIEW_DECISIONS)}"
                    )
                coverage_verdict = None
                duplicate_of = None
                if schema_version in {8, 9}:
                    coverage_verdict = review.get("coverage_verdict")
                    if coverage_verdict not in COVERAGE_VERDICTS:
                        raise ValueError(
                            f"shortlist_reviews[{review_index}].coverage_verdict must be one of "
                            f"{sorted(COVERAGE_VERDICTS)}"
                        )
                    duplicate_of = review.get("duplicate_of")
                    if coverage_verdict == "confirmed" and decision != "select":
                        raise ValueError(
                            f"confirmed coverage must be selected: {bundle_id}"
                        )
                    if coverage_verdict in {"refuted", "duplicate"} and decision != "omit":
                        raise ValueError(
                            f"{coverage_verdict} coverage must be omitted: {bundle_id}"
                        )
                    if (
                        coverage_verdict == "refuted"
                        and protocol_status_by_id.get(bundle_id) == "confirmed"
                    ):
                        raise ValueError(
                            f"confirmed catalog coverage cannot be refuted during retrieval: {bundle_id}"
                        )
                    if coverage_verdict == "duplicate":
                        if (
                            not isinstance(duplicate_of, str)
                            or duplicate_of not in normalized_shortlist
                            or duplicate_of == bundle_id
                        ):
                            raise ValueError(
                                f"duplicate review requires another shortlisted duplicate_of: {bundle_id}"
                            )
                        duplicate_targets[bundle_id] = duplicate_of
                    elif duplicate_of is not None:
                        raise ValueError(
                            f"duplicate_of must be null unless coverage_verdict is duplicate: {bundle_id}"
                        )
                marginal_value = _concrete_text(
                    review,
                    "marginal_value",
                    review_index,
                    CONCRETENESS_MINIMUMS["shortlist_reviews.marginal_value"],
                )
                boundary = _concrete_text(
                    review,
                    "boundary",
                    review_index,
                    CONCRETENESS_MINIMUMS["shortlist_reviews.boundary"],
                )
                evidence = review.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    raise ValueError(
                        f"shortlist_reviews[{review_index}].evidence must not be empty"
                    )
                checked_evidence = []
                for evidence_index, citation in enumerate(evidence):
                    if not isinstance(citation, dict):
                        raise ValueError(
                            f"shortlist_reviews[{review_index}].evidence[{evidence_index}] "
                            "must be an object"
                        )
                    relative = citation.get("path")
                    start = citation.get("line_start")
                    end = citation.get("line_end")
                    excerpt = citation.get("excerpt")
                    if not isinstance(relative, str):
                        raise ValueError(
                            f"shortlist_reviews[{review_index}] evidence path is missing"
                        )
                    if (
                        not isinstance(start, int)
                        or not isinstance(end, int)
                        or start < 1
                        or end < start
                    ):
                        raise ValueError(
                            f"shortlist_reviews[{review_index}] evidence line range is invalid"
                        )
                    source = _inside(library, relative)
                    lines = source.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if end > len(lines):
                        raise ValueError(
                            f"shortlist_reviews[{review_index}] evidence line range exceeds {relative}"
                        )
                    cited = "\n".join(lines[start - 1 : end])
                    if (
                        not isinstance(excerpt, str)
                        or not excerpt.strip()
                        or excerpt.strip() not in cited
                    ):
                        raise ValueError(
                            f"shortlist_reviews[{review_index}] evidence excerpt is not exact in "
                            f"{relative}"
                        )
                    checked_evidence.append({
                        "path": relative,
                        "line_start": start,
                        "line_end": end,
                        "excerpt": excerpt.strip(),
                    })
                if decision == "select":
                    reviewed_selected_ids.add(bundle_id)
                normalized_reviews.append({
                    "bundle_id": bundle_id,
                    "decision": decision,
                    "marginal_value": marginal_value,
                    "boundary": boundary,
                    "evidence": checked_evidence,
                    **({
                        "coverage_verdict": coverage_verdict,
                        "duplicate_of": duplicate_of,
                    } if schema_version in {8, 9} else {}),
                })
            if set(review_ids) != set(normalized_shortlist):
                missing = sorted(set(normalized_shortlist) - set(review_ids))
                raise ValueError(
                    "shortlist_reviews must cover every shortlisted component exactly once; "
                    f"missing={missing}"
                )

    selected = value.get("selected")
    maximum = min(5, len(valid_ids))
    if not isinstance(selected, list) or len(selected) > maximum:
        raise ValueError(f"selected must contain between 0 and {maximum} components")

    seen: set[str] = set()
    seen_source_digests: dict[str, str] = {}
    seen_entrypoint_families: dict[tuple[str, ...], str] = {}
    normalized = []
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            raise ValueError(f"selected[{index}] must be an object")
        bundle_id = item.get("bundle_id")
        if bundle_id not in valid_ids:
            raise ValueError(f"selected[{index}] has unknown bundle_id: {bundle_id!r}")
        if bundle_id in seen:
            raise ValueError(f"selected[{index}] repeats bundle_id: {bundle_id}")
        seen.add(bundle_id)
        if schema_version in {5, 6, 7, 8, 9} and bundle_id not in normalized_shortlist:
            raise ValueError(f"selected[{index}] must first appear in shortlisted_bundle_ids")

        source_digest = source_digest_by_id.get(bundle_id)
        if source_digest is not None and source_digest in seen_source_digests:
            raise ValueError(
                f"selected[{index}] duplicates source content from "
                f"{seen_source_digests[source_digest]}"
            )
        if source_digest is not None:
            seen_source_digests[source_digest] = bundle_id
        entrypoint_family = entrypoint_family_by_id.get(bundle_id)
        if entrypoint_family is not None and entrypoint_family in seen_entrypoint_families:
            raise ValueError(
                f"selected[{index}] duplicates entrypoint family from "
                f"{seen_entrypoint_families[entrypoint_family]}: "
                + ", ".join(entrypoint_family)
            )
        if entrypoint_family is not None:
            seen_entrypoint_families[entrypoint_family] = bundle_id

        delivery_mode = item.get("delivery_mode")
        if delivery_mode not in DELIVERY_MODES:
            raise ValueError(
                f"selected[{index}].delivery_mode must be one of {sorted(DELIVERY_MODES)}"
            )
        task_overlap = _concrete_text(
            item, "task_overlap", index, CONCRETENESS_MINIMUMS["selected.task_overlap"]
        )
        incremental_contribution = _concrete_text(
            item,
            "incremental_contribution",
            index,
            CONCRETENESS_MINIMUMS["selected.incremental_contribution"],
        )
        usage = _concrete_text(item, "usage", index, CONCRETENESS_MINIMUMS["selected.usage"])
        boundary = _concrete_text(
            item, "boundary", index, CONCRETENESS_MINIMUMS["selected.boundary"]
        )

        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"selected[{index}].evidence must not be empty")
        checked_evidence = []
        for evidence_index, citation in enumerate(evidence):
            if not isinstance(citation, dict):
                raise ValueError(
                    f"selected[{index}].evidence[{evidence_index}] must be an object"
                )
            relative = citation.get("path")
            start = citation.get("line_start")
            end = citation.get("line_end")
            excerpt = citation.get("excerpt")
            if not isinstance(relative, str):
                raise ValueError(f"selected[{index}] evidence path is missing")
            if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
                raise ValueError(f"selected[{index}] evidence line range is invalid")
            source = _inside(library, relative)
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
            if end > len(lines):
                raise ValueError(f"selected[{index}] evidence line range exceeds {relative}")
            cited = "\n".join(lines[start - 1 : end])
            if not isinstance(excerpt, str) or not excerpt.strip() or excerpt.strip() not in cited:
                raise ValueError(f"selected[{index}] evidence excerpt is not exact in {relative}")
            checked_evidence.append({
                "path": relative,
                "line_start": start,
                "line_end": end,
                "excerpt": excerpt.strip(),
            })

        normalized.append({
            "bundle_id": bundle_id,
            "delivery_mode": delivery_mode,
            "task_overlap": task_overlap,
            "incremental_contribution": incremental_contribution,
            "usage": usage,
            "boundary": boundary,
            "evidence": checked_evidence,
        })

    if schema_version in {7, 8, 9} and seen != reviewed_selected_ids:
        raise ValueError("selected IDs must exactly match shortlist_reviews select decisions")
    if schema_version in {8, 9}:
        for bundle_id, duplicate_of in duplicate_targets.items():
            if duplicate_of not in seen:
                raise ValueError(
                    f"duplicate review target must be selected: {bundle_id} -> {duplicate_of}"
                )

    normalized_propagation_checks = None
    if schema_version == 9:
        checks = value.get("propagation_checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("propagation_checks must be a non-empty list")
        introduced_variants = set(
            normalized_change_model["introduced_or_changed_variants"]
        )
        covered_variants: set[str] = set()
        covered_selected: set[str] = set()
        normalized_propagation_checks = []
        for check_index, check in enumerate(checks):
            if not isinstance(check, dict):
                raise ValueError(f"propagation_checks[{check_index}] must be an object")
            carrier = check.get("carrier")
            if (
                not isinstance(carrier, str)
                or len(carrier.strip()) < CONCRETENESS_MINIMUMS["propagation_checks.carrier"]
            ):
                raise ValueError(
                    f"propagation_checks[{check_index}].carrier must be role-independent"
                )
            variants = _concrete_string_list(
                check.get("changed_variants"),
                f"propagation_checks[{check_index}].changed_variants",
                minimum_length=CONCRETENESS_MINIMUMS["propagation_checks.changed_variants"],
            )
            unknown_variants = set(variants) - introduced_variants
            if unknown_variants:
                raise ValueError(
                    f"propagation_checks[{check_index}] references unknown variants: "
                    f"{sorted(unknown_variants)}"
                )
            bundle_ids = _concrete_string_list(
                check.get("bundle_ids"),
                f"propagation_checks[{check_index}].bundle_ids",
                minimum_length=CONCRETENESS_MINIMUMS["propagation_checks.bundle_ids"],
            )
            unknown_bundles = set(bundle_ids) - seen
            if unknown_bundles:
                raise ValueError(
                    f"propagation_checks[{check_index}] references unselected bundles: "
                    f"{sorted(unknown_bundles)}"
                )
            symbols = _concrete_string_list(
                check.get("symbols"),
                f"propagation_checks[{check_index}].symbols",
                minimum_length=CONCRETENESS_MINIMUMS["propagation_checks.symbols"],
            )
            argument_positions = _concrete_string_list(
                check.get("argument_positions"),
                f"propagation_checks[{check_index}].argument_positions",
                minimum_length=CONCRETENESS_MINIMUMS["propagation_checks.argument_positions"],
            )
            invariant = check.get("invariant")
            if (
                not isinstance(invariant, str)
                or len(invariant.strip())
                < CONCRETENESS_MINIMUMS["propagation_checks.invariant"]
            ):
                raise ValueError(
                    f"propagation_checks[{check_index}].invariant must be concrete"
                )
            evidence = check.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(
                    f"propagation_checks[{check_index}].evidence must not be empty"
                )
            checked_evidence = []
            for evidence_index, citation in enumerate(evidence):
                if not isinstance(citation, dict):
                    raise ValueError(
                        f"propagation_checks[{check_index}].evidence[{evidence_index}] "
                        "must be an object"
                    )
                relative = citation.get("path")
                start = citation.get("line_start")
                end = citation.get("line_end")
                excerpt = citation.get("excerpt")
                if not isinstance(relative, str):
                    raise ValueError(
                        f"propagation_checks[{check_index}] evidence path is missing"
                    )
                if (
                    not isinstance(start, int)
                    or not isinstance(end, int)
                    or start < 1
                    or end < start
                ):
                    raise ValueError(
                        f"propagation_checks[{check_index}] evidence line range is invalid"
                    )
                source = _inside(library, relative)
                lines = source.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if end > len(lines):
                    raise ValueError(
                        f"propagation_checks[{check_index}] evidence line range exceeds {relative}"
                    )
                cited = "\n".join(lines[start - 1 : end])
                if (
                    not isinstance(excerpt, str)
                    or not excerpt.strip()
                    or excerpt.strip() not in cited
                ):
                    raise ValueError(
                        f"propagation_checks[{check_index}] evidence excerpt is not exact in "
                        f"{relative}"
                    )
                checked_evidence.append({
                    "path": relative,
                    "line_start": start,
                    "line_end": end,
                    "excerpt": excerpt.strip(),
                })
            covered_variants.update(variants)
            covered_selected.update(bundle_ids)
            normalized_propagation_checks.append({
                "carrier": carrier.strip(),
                "changed_variants": variants,
                "bundle_ids": bundle_ids,
                "symbols": symbols,
                "argument_positions": argument_positions,
                "invariant": invariant.strip(),
                "evidence": checked_evidence,
            })
        if covered_variants != introduced_variants:
            missing = sorted(introduced_variants - covered_variants)
            raise ValueError(
                "propagation_checks must cover every introduced variant; "
                f"missing={missing}"
            )
        if covered_selected != seen:
            missing = sorted(seen - covered_selected)
            raise ValueError(
                "propagation_checks must cover every selected component; "
                f"missing={missing}"
            )

    result = {
        "schema_version": schema_version,
        "task_id": task_id,
        "method": "marginal_value_retrieval_over_frozen_component_library",
        "task_baseline": {
            "explicit_information": normalized_explicit,
            "obvious_scope": obvious_scope.strip(),
        },
        "selected": normalized,
        "selected_bundle_ids": [item["bundle_id"] for item in normalized],
    }
    if schema_version in {5, 6, 7, 8, 9}:
        result.update({
            "method": "complete_catalog_scan_then_grounded_marginal_value_retrieval",
            "change_model": normalized_change_model,
            "component_assessments": normalized_assessments,
            "shortlisted_bundle_ids": normalized_shortlist,
        })
    if schema_version in {6, 7, 8, 9}:
        result.update({
            "method": "staged_protocol_coverage_then_marginal_value_retrieval",
            "coverage_sha256": coverage_digest,
            "protocol_coverage": normalized_coverage,
        })
    if schema_version in {7, 8, 9}:
        result.update({
            "method": "staged_protocol_coverage_then_evidenced_marginal_value_retrieval",
            "shortlist_reviews": normalized_reviews,
        })
    if schema_version in {8, 9}:
        result["method"] = "staged_protocol_coverage_then_adjudicated_marginal_value_retrieval"
    if schema_version == 9:
        result.update({
            "method": "staged_protocol_coverage_with_propagation_closure_retrieval",
            "propagation_checks": normalized_propagation_checks,
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--check-coverage", action="store_true")
    parser.add_argument("--task-id")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_coverage:
            if args.coverage is None:
                parser.error("--check-coverage requires --coverage")
            result = validate_coverage(
                args.library,
                args.coverage,
                expected_task_id=args.task_id,
            )
            print("COVERAGE_VALID_CONTINUE_SELECTION")
            return 0
        if args.selection is None:
            parser.error("--selection is required unless --check-coverage is used")
        result = validate_selection(
            args.library,
            args.selection,
            expected_task_id=args.task_id,
            coverage_path=args.coverage,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Submission check failed: {exc}. Fix selection.json and check again.")
        return 1
    if args.submit:
        print("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")
    else:
        print(json.dumps({"status": "valid", "selected_bundle_ids": result["selected_bundle_ids"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
