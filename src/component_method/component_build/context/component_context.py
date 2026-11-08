"""Generate and validate task-blind guidance for mined component candidates."""

from __future__ import annotations

import builtins
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .json_utils import extract_json_object, require_library_schema
from .llm_client import DeepSeekClient
from .support import PROMPT_DIR, build_user_prompt, read_text, save_call_log, write_json
from component_method.source_scan.units import source_unit_records

CONTEXT_SYSTEM = PROMPT_DIR / "component_context_system.txt"
CONTEXT_USER = PROMPT_DIR / "component_context_user_template.txt"
CONTEXT_GATE_SYSTEM = PROMPT_DIR / "component_review_system.txt"
CONTEXT_GATE_USER = PROMPT_DIR / "component_review_user_template.txt"
MAX_CONTEXT_EXTRACTION_ATTEMPTS = 3
MAX_PREVIOUS_RESPONSE_CHARS = 12000


def _prompt_meta() -> dict[str, str]:
    return {
        "gate_system": hashlib.sha256(CONTEXT_GATE_SYSTEM.read_bytes()).hexdigest(),
        "gate_user": hashlib.sha256(CONTEXT_GATE_USER.read_bytes()).hexdigest(),
        "common_system": hashlib.sha256(CONTEXT_SYSTEM.read_bytes()).hexdigest(),
        "common_user": hashlib.sha256(CONTEXT_USER.read_bytes()).hexdigest(),
    }


def _validate_context_common(payload: dict[str, Any]) -> None:
    if payload.get("status") != "draft_ready":
        raise ValueError("component context must return status='draft_ready'")
    require_library_schema(payload)
    guidance = payload.get("agent_guidance")
    if not isinstance(guidance, dict):
        raise ValueError("component context must include agent_guidance")
    if not isinstance(guidance.get("summary"), str):
        raise ValueError("agent_guidance.summary must be a string")
    for field in ("invariants", "variation_points", "pitfalls", "recommended_use"):
        values = guidance.get(field)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError(f"agent_guidance.{field} must be a list of strings")


def _call_context_common(
    client: DeepSeekClient,
    cluster: dict[str, Any],
    dataset_dir: Path,
    out_dir: Path,
    subcluster: dict[str, Any],
    *,
    attempt: int = 1,
    validation_feedback: str | None = None,
    previous_response: str | None = None,
) -> dict[str, Any]:
    members = set(subcluster["members"])
    payload = {
        "cluster_id": cluster["cluster_id"],
        "subcluster": subcluster,
        "files": [
            {
                "file_id": item["file_id"],
                "rel_path": item["rel_path"],
                "source_code": (
                    dataset_dir / "clusters" / cluster["cluster_id"] / "original" / item["file_id"]
                ).read_text(encoding="utf-8"),
            }
            for item in cluster["files"]
            if item["file_id"] in members
        ],
    }
    system_prompt = read_text(CONTEXT_SYSTEM)
    user_prompt = build_user_prompt(CONTEXT_USER, payload)
    if validation_feedback:
        user_prompt += (
            "\n\nYour previous draft did not pass private local validation. "
            "You cannot inspect or invoke that validator. Revise the complete artifact "
            "using only this feedback, then return a new draft. Do not claim it passed.\n"
            "Validation feedback:\n"
            + validation_feedback
        )
    if previous_response:
        user_prompt += (
            "\n\nPrevious draft to revise:\n"
            + previous_response[:MAX_PREVIOUS_RESPONSE_CHARS]
        )
    prompt_paths = {"system": str(CONTEXT_SYSTEM), "user_template": str(CONTEXT_USER)}
    response = client.chat(system_prompt, user_prompt)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if attempt == 1 else f".retry{attempt - 1}"
    (out_dir / f"component_context_raw_response{suffix}.txt").write_text(
        response.content, encoding="utf-8"
    )
    write_json(out_dir / f"component_context_raw_api_response{suffix}.json", response.raw)
    save_call_log(
        out_dir / f"component_context_call_log{suffix}.json",
        response,
        "component_context",
        subcluster["cluster_id"],
        prompt_paths,
    )
    result = extract_json_object(response.content)
    _validate_context_common(result)
    return result


def _validation_feedback(validation: dict[str, Any]) -> str:
    fields = (
        "status",
        "reason",
        "compile",
        "invented_imports",
        "undefined_names",
    )
    summary = {field: validation[field] for field in fields if field in validation}
    return json.dumps(summary, ensure_ascii=False, indent=2)


def run_context_extraction_loop(
    client: DeepSeekClient,
    cluster: dict[str, Any],
    dataset_dir: Path,
    out_dir: Path,
    subcluster: dict[str, Any],
    source_by_id: dict[str, str],
    *,
    max_attempts: int = MAX_CONTEXT_EXTRACTION_ATTEMPTS,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Generate, locally validate, and repair one accepted component pattern."""
    max_attempts = max(1, int(max_attempts))
    attempts: list[dict[str, Any]] = []
    feedback: str | None = None
    previous_response: str | None = None
    last_validation: dict[str, Any] = {}

    for attempt in range(1, max_attempts + 1):
        attempt_dir = out_dir / "attempts" / f"attempt_{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] | None = None
        try:
            payload = _call_context_common(
                client,
                cluster,
                dataset_dir,
                attempt_dir,
                subcluster,
                attempt=attempt,
                validation_feedback=feedback,
                previous_response=previous_response,
            )
            validation = _validate_common_reference(
                payload,
                subcluster,
                source_by_id,
                attempt_dir,
            )
        except Exception as exc:  # Each failed draft becomes feedback for the next attempt.
            validation = {
                "subcluster_id": subcluster["cluster_id"],
                "status": "generation_failed",
                "reason": repr(exc),
            }

        write_json(attempt_dir / "validation.json", validation)
        last_validation = validation
        attempt_record = {
            "attempt": attempt,
            "status": validation.get("status"),
        }
        for field in ("reason", "compile", "invented_imports", "undefined_names"):
            if field in validation:
                attempt_record[field] = validation[field]
        attempts.append(attempt_record)

        if validation.get("status") == "ok" and payload is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "common.py").write_text(
                payload["library"]["content"],
                encoding="utf-8",
            )
            final_validation = {
                **validation,
                "attempt_count": attempt,
                "attempts": attempts,
            }
            write_json(out_dir / "validation.json", final_validation)
            return payload, final_validation

        feedback = _validation_feedback(validation)
        if payload is not None:
            previous_response = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            suffix = "" if attempt == 1 else f".retry{attempt - 1}"
            raw_path = attempt_dir / f"component_context_raw_response{suffix}.txt"
            previous_response = (
                raw_path.read_text(encoding="utf-8")[:MAX_PREVIOUS_RESPONSE_CHARS]
                if raw_path.is_file()
                else None
            )

    if last_validation.get("status") in {"compile_failed", "empty", "ungrounded"}:
        final_validation = {
            **last_validation,
            "status": "repair_exhausted",
            "reason": (
                f"Local validation still failed after {max_attempts} extraction attempts: "
                f"{last_validation.get('reason', last_validation.get('status'))}"
            ),
            "attempt_count": max_attempts,
            "attempts": attempts,
        }
    else:
        final_validation = {
            "subcluster_id": subcluster["cluster_id"],
            "status": "generation_failed",
            "reason": f"No valid extraction draft after {max_attempts} attempts",
            "attempt_count": max_attempts,
            "attempts": attempts,
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "validation.json", final_validation)
    return None, final_validation


from component_method.languages.python.grounding import (
    _member_evidence, _stdlib_module_roots, _STDLIB_MODULE_ROOTS,
    _undefined_names, _validate_common_reference,
)

def _load_source_units(source: str, unit_ids: list[str]) -> list[dict[str, Any]]:
    records = source_unit_records(source)
    by_id = {record["unit_id"]: record for record in records}
    selected = []
    for unit_id in unit_ids or ["module"]:
        record = by_id.get(unit_id)
        if record is not None:
            selected.append({
                "unit_id": unit_id,
                "start": record["start"],
                "end": record["end"],
                "content": record["source_code"],
            })
    if selected:
        return selected
    return [{
        "unit_id": "module",
        "start": 1,
        "end": max(1, len(source.splitlines())),
        "content": source,
    }]


def _write_snippets(
    context_root: Path,
    subcluster: dict[str, Any],
    file_by_id: dict[str, dict[str, Any]],
    source_by_id: dict[str, str],
) -> Path:
    path = context_root / "snippets" / f"{subcluster['cluster_id']}.md"
    lines = [f"# Source evidence: {subcluster['cluster_id']}", ""]
    for file_id in subcluster["members"]:
        entry = file_by_id[file_id]
        lines.extend([f"## `{entry['rel_path']}`", ""])
        unit_ids = subcluster.get("units", {}).get(file_id, [])
        for unit in _load_source_units(source_by_id[file_id], unit_ids):
            lines.extend([
                f"### `{unit['unit_id']}` (lines {unit['start']}-{unit['end']})",
                "",
                "```python",
                unit["content"].rstrip("\n"),
                "```",
                "",
            ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
