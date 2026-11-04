from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
        if match:
            text = match.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON root must be an object")
    return payload


def require_extraction_schema(payload: dict[str, Any]) -> None:
    library = payload.get("library")
    members = payload.get("members")
    if not isinstance(library, dict) or not isinstance(library.get("content"), str):
        raise ValueError("Extraction output must include library.content")
    if not isinstance(members, dict):
        raise ValueError("Extraction output must include members object")
    for file_id, member in members.items():
        if not isinstance(file_id, str) or not isinstance(member, dict):
            raise ValueError("Each members entry must be an object")
        forbidden = {"diff", "new_content", "edit_mapping", "call_mapping"} & set(member)
        if forbidden:
            raise ValueError(f"{file_id} must contain edit intents only; unexpected fields: {sorted(forbidden)}")
        if not isinstance(member.get("edits"), list):
            raise ValueError(f"{file_id} missing edits list")
        for edit in member["edits"]:
            if not isinstance(edit, dict):
                raise ValueError(f"{file_id} edits entries must be objects")
            if not isinstance(edit.get("original"), str) or not edit["original"]:
                raise ValueError(f"{file_id} edit entry missing non-empty original fragment")
            if not isinstance(edit.get("replacement"), str):
                raise ValueError(f"{file_id} edit entry missing replacement fragment")
            if "rationale" in edit and not isinstance(edit["rationale"], str):
                raise ValueError(f"{file_id} edit rationale must be a string")
        if "rationale" in member and not isinstance(member["rationale"], str):
            raise ValueError(f"{file_id} rationale must be a string")


def require_library_schema(payload: dict[str, Any]) -> None:
    library = payload.get("library")
    if not isinstance(library, dict) or not isinstance(library.get("content"), str):
        raise ValueError("Library output must include library.content")
    path = library.get("path")
    if path is not None and not isinstance(path, str):
        raise ValueError("Library output library.path must be a string")
    rationale = payload.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise ValueError("Library output rationale must be a string")


def require_member_refactor_schema(payload: dict[str, Any], expected_file_id: str | None = None) -> None:
    file_id = payload.get("file_id")
    if not isinstance(file_id, str):
        raise ValueError("Member refactor output must include file_id")
    if expected_file_id is not None and file_id != expected_file_id:
        raise ValueError(f"Member refactor file_id mismatch: expected {expected_file_id}, got {file_id}")
    forbidden = {"diff", "new_content", "edit_mapping", "call_mapping"} & set(payload)
    if forbidden:
        raise ValueError(f"Member refactor must contain edit intents only; unexpected fields: {sorted(forbidden)}")
    if not isinstance(payload.get("edits"), list):
        raise ValueError("Member refactor output must include edits list")
    for edit in payload["edits"]:
        if not isinstance(edit, dict):
            raise ValueError("Member refactor edits entries must be objects")
        if not isinstance(edit.get("original"), str) or not edit["original"]:
            raise ValueError("Member refactor edit entry missing non-empty original fragment")
        if not isinstance(edit.get("replacement"), str):
            raise ValueError("Member refactor edit entry missing replacement fragment")
        if "rationale" in edit and not isinstance(edit["rationale"], str):
            raise ValueError("Member refactor edit rationale must be a string")
    rationale = payload.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise ValueError("Member refactor rationale must be a string")


def require_refactor_batch_schema(payload: dict[str, Any], expected_file_ids: set[str]) -> None:
    refactors = payload.get("refactors")
    if not isinstance(refactors, list) or not refactors:
        raise ValueError("Refactor output must include a non-empty refactors list")
    got: set[str] = set()
    for item in refactors:
        require_member_refactor_schema(item)
        if item["file_id"] in got:
            raise ValueError(f"Refactor output contains duplicate file_id: {item['file_id']}")
        got.add(item["file_id"])
    if got != set(expected_file_ids):
        raise ValueError(
            f"Refactor output file_ids mismatch: expected {sorted(expected_file_ids)}, got {sorted(got)}"
        )


def require_discovery_schema(payload: dict[str, Any]) -> None:
    clusters = payload.get("clusters")
    if not isinstance(clusters, list):
        raise ValueError("Discovery output must include clusters list")
    for item in clusters:
        if not isinstance(item, dict):
            raise ValueError("Each discovered cluster must be an object")
        if not isinstance(item.get("cluster_id"), str):
            raise ValueError("Discovered cluster missing cluster_id")
        if not isinstance(item.get("members"), list):
            raise ValueError("Discovered cluster missing members list")
