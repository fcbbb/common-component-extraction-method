"""Freeze accepted extraction drafts into a deterministic review candidate set."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from component_method.component_build.contracts import normalize_component_draft


def candidate_member_key(candidate: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return the exact source-member identity used for conservative deduplication."""
    return tuple(sorted(
        (member["file_id"], member["unit_id"])
        for member in candidate.get("members", [])
    ))


def stable_candidate_id(candidate: dict[str, Any]) -> str:
    """Derive the historical component ID from members and the retained name."""
    identity = {
        "members": candidate_member_key(candidate),
        "name": candidate.get("name", ""),
    }
    digest = hashlib.sha1(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]
    return f"component_{digest}"


def accepted_extraction_records(extraction_root: Path) -> list[dict[str, Any]]:
    """Load only component IDs accepted by each extraction batch's schema check."""
    records: list[dict[str, Any]] = []
    for batch_dir in sorted(path for path in extraction_root.iterdir() if path.is_dir()):
        response_path = batch_dir / "extraction_response.json"
        validation_path = batch_dir / "extraction_schema_validation.json"
        if not response_path.is_file() or not validation_path.is_file():
            continue
        response = json.loads(response_path.read_text(encoding="utf-8"))
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        accepted = set(validation.get("accepted_component_ids", []))
        for component in response.get("components", []):
            if component.get("component_id") in accepted:
                records.append({
                    "batch_id": batch_dir.name,
                    "source_component_id": component["component_id"],
                    "component": component,
                })
    return records


def freeze_extraction_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize and exactly deduplicate accepted drafts without task information."""
    by_members: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
    duplicate_groups: dict[tuple[tuple[str, str], ...], list[dict[str, str]]] = {}
    for record in records:
        batch_id = record["batch_id"]
        source_component_id = record["source_component_id"]
        component = deepcopy(record["component"])
        component["region_id"] = batch_id
        component["source_region_ids"] = [batch_id]
        key = candidate_member_key(component)
        if not key:
            continue
        source_ref = {
            "batch_id": batch_id,
            "component_id": source_component_id,
        }
        duplicate_groups.setdefault(key, []).append(source_ref)
        if key not in by_members:
            component["candidate_id"] = stable_candidate_id(component)
            component["source_regions"] = [batch_id]
            component["source_extractions"] = [source_ref]
            component["component_draft"] = normalize_component_draft(
                component,
                component_id=component["candidate_id"],
                origin_strategy="protocol_candidate_blind_extraction",
            ).to_json()
            by_members[key] = component
            continue

        retained = by_members[key]
        retained["source_regions"] = sorted(set(retained["source_regions"]) | {batch_id})
        retained["source_extractions"].append(source_ref)
        for field in ("evidence",):
            retained[field] = retained.get(field, []) + component.get(field, [])
        for field in ("relationships", "limitations"):
            retained[field] = sorted(set(retained.get(field, [])) | set(component.get(field, [])))

    candidates = sorted(by_members.values(), key=lambda item: item["candidate_id"])
    duplicate_rows = [
        {
            "members": [
                {"file_id": file_id, "unit_id": unit_id}
                for file_id, unit_id in key
            ],
            "source_extractions": refs,
            "retained_candidate_id": by_members[key]["candidate_id"],
        }
        for key, refs in sorted(duplicate_groups.items())
        if len(refs) > 1
    ]
    manifest = {
        "schema": "frozen-blind-component-candidates-v1",
        "selection_policy": "accepted_schema_then_exact_source_member_deduplication",
        "task_information_used": False,
        "accepted_extraction_count": len(records),
        "frozen_candidate_count": len(candidates),
        "duplicates_removed": len(records) - len(candidates),
        "duplicate_groups": duplicate_rows,
    }
    return candidates, manifest


def freeze_extraction_directory(extraction_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and freeze one directory containing extraction batch outputs."""
    return freeze_extraction_records(accepted_extraction_records(extraction_root))
