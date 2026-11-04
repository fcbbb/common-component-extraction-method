from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
from typing import Any

from component_method.runtime_paths import release_root

PROJECT = release_root()
ROOT = Path(os.environ.get("COMPONENT_METHOD_TASK_ROOT", Path.cwd())).resolve()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit_key(unit: dict[str, str]) -> tuple[str, str]:
    return unit.get("file_id", ""), unit.get("unit_id", "")


def validate_protocol_contracts(
    response: dict[str, Any],
    *,
    packet: dict[str, Any],
    repository_root: Path,
    schema_path: Path,
) -> dict[str, Any]:
    schema = load_json(schema_path)
    required = set(schema["required_fields"])
    consumer_required = set(schema["consumer_required_fields"])
    focus = {unit_key(unit) for unit in packet["focus_units"]}
    rows = []
    all_errors = []

    for component in response.get("components", []):
        component_id = component.get("component_id", "")
        errors = []
        members = {
            unit_key(unit)
            for unit in component.get("members", [])
            if isinstance(unit, dict)
        }
        if not members & focus:
            errors.append("component has no exact focus member")

        contract = component.get("protocol_contract")
        if not isinstance(contract, dict):
            errors.append("protocol_contract must be an object")
            contract = {}
        missing = sorted(required - set(contract))
        extra = sorted(set(contract) - required)
        if missing:
            errors.append(f"protocol_contract missing fields: {missing}")
        if extra:
            errors.append(f"protocol_contract has unsupported fields: {extra}")

        for field in (
            "capability_family",
            "semantic_domain",
            "extension_trigger",
            "downstream_guarantee",
            "boundary",
        ):
            if not isinstance(contract.get(field), str) or not contract.get(field, "").strip():
                errors.append(f"protocol_contract.{field} must be a non-empty string")

        variants = contract.get("covered_variants")
        if not isinstance(variants, list) or not variants or not all(
            isinstance(item, str) and item.strip() for item in variants
        ):
            errors.append("protocol_contract.covered_variants must be a non-empty string list")

        evidence_files = {
            item.get("file_id")
            for item in component.get("evidence", [])
            if isinstance(item, dict)
        }
        consumers = contract.get("consumers")
        consumer_keys = []
        if not isinstance(consumers, list) or len(consumers) < schema["minimum_consumer_count"]:
            errors.append(
                "protocol_contract.consumers must contain at least "
                f"{schema['minimum_consumer_count']} entries"
            )
            consumers = consumers if isinstance(consumers, list) else []
        for index, consumer in enumerate(consumers):
            if not isinstance(consumer, dict):
                errors.append(f"consumer {index} must be an object")
                continue
            missing_consumer = sorted(consumer_required - set(consumer))
            if missing_consumer:
                errors.append(f"consumer {index} missing fields: {missing_consumer}")
                continue
            if not all(
                isinstance(consumer.get(field), str) and consumer[field].strip()
                for field in consumer_required
            ):
                errors.append(f"consumer {index} fields must be non-empty strings")
                continue
            key = unit_key(consumer)
            consumer_keys.append(key)
            source_path = repository_root / consumer["file_id"]
            if not source_path.is_file():
                errors.append(f"consumer {index} file does not exist: {consumer['file_id']}")
            if consumer["file_id"] not in evidence_files:
                errors.append(
                    f"consumer {index} file lacks an evidence citation: {consumer['file_id']}"
                )
        if len(consumer_keys) != len(set(consumer_keys)):
            errors.append("protocol_contract.consumers contains duplicate source units")

        reuse = contract.get("reuse_interface")
        if not isinstance(reuse, dict):
            errors.append("protocol_contract.reuse_interface must be an object")
        else:
            mode = reuse.get("mode")
            value = reuse.get("value")
            if mode not in schema["reuse_modes"]:
                errors.append(f"unsupported reuse_interface mode: {mode!r}")
            if not isinstance(value, str) or not value.strip():
                errors.append("reuse_interface.value must be a non-empty string")
            if mode == "stable_entrypoint":
                entrypoints = {
                    entry.get("name")
                    for entry in component.get("entrypoints", [])
                    if isinstance(entry, dict)
                }
                if value not in entrypoints:
                    errors.append(
                        "stable_entrypoint value is not a declared component entrypoint"
                    )

        row = {
            "component_id": component_id,
            "focus_member_count": len(members & focus),
            "consumer_count": len(consumers),
            "capability_family": contract.get("capability_family"),
            "reuse_mode": reuse.get("mode") if isinstance(reuse, dict) else None,
            "status": "ok" if not errors else "invalid",
            "errors": errors,
        }
        rows.append(row)
        all_errors.extend(
            {"component_id": component_id, "error": error} for error in errors
        )

    if not rows:
        all_errors.append({"component_id": None, "error": "packet published no components"})
    return {
        "schema": "protocol-contract-validation-v1",
        "status": "ok" if not all_errors else "invalid",
        "component_count": len(rows),
        "valid_component_count": sum(row["status"] == "ok" for row in rows),
        "components": rows,
        "errors": all_errors,
    }


def render_component_readme(component: dict[str, Any]) -> str:
    contract = component["protocol_contract"]
    lines = [
        f"# {component.get('name') or component['component_id']}",
        "",
        component.get("summary", ""),
        "",
        f"- Internal ID: `{component['component_id']}`",
        f"- Capability family: `{contract['capability_family']}`",
        "",
        "## Stable entrypoints",
        "",
    ]
    for entry in component.get("entrypoints", []):
        lines.append(
            f"- `{entry['name']}` ({entry['kind']}): {entry.get('purpose', '')}"
        )
    lines.extend(["", "## Protocol contract", ""])
    for field in (
        "semantic_domain",
        "extension_trigger",
        "covered_variants",
        "downstream_guarantee",
        "consumers",
        "reuse_interface",
        "boundary",
    ):
        lines.extend(
            [f"### {field}", "", json.dumps(contract[field], ensure_ascii=False, indent=2), ""]
        )
    lines.extend(["## Source evidence", ""])
    for evidence in component.get("evidence", []):
        lines.append(
            f"- `{evidence['file_id']}:{evidence['line_start']}-{evidence['line_end']}`: "
            f"{evidence['claim']}"
        )
    return "\n".join(lines) + "\n"
