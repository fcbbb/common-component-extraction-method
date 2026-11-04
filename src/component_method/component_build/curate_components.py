#!/usr/bin/env python3
"""Admit valid components without rejecting their whole extraction packet."""

from __future__ import annotations

from copy import deepcopy
import json

from component_method.workflow.experiment_common import (
    PROJECT,
    ROOT,
    load_json,
    sha256,
    unit_key,
    validate_protocol_contracts,
    write_json,
)


def main() -> None:
    config = load_json(ROOT / "config.json")
    extraction_root = ROOT / "runs" / config["task_id"] / "extraction_v1"
    raw_summary_path = extraction_root / "summary.json"
    raw_summary = load_json(raw_summary_path)
    packets_payload = load_json(ROOT / "inputs" / "focus_context_packets.json")
    packets = {packet["packet_id"]: packet for packet in packets_payload["packets"]}
    schema_path = PROJECT / config["protocol_contract_schema"]
    repository_root = PROJECT / config["repository_root"]
    curated_root = extraction_root / "curated"
    summary_path = curated_root / "summary.json"

    if summary_path.is_file():
        existing = load_json(summary_path)
        if existing.get("raw_summary_sha256") == sha256(raw_summary_path):
            print(json.dumps(existing, ensure_ascii=False, indent=2))
            return
        raise RuntimeError(f"preserving different curated extraction: {curated_root}")

    packet_reports = []
    excluded_packets = []
    retained_ids = []
    seen_ids = set()
    raw_component_count = 0

    for packet_id in raw_summary["packet_ids"]:
        packet = packets[packet_id]
        raw_path = extraction_root / "packets" / packet_id / "extraction_response.json"
        raw = load_json(raw_path)
        focus = {unit_key(unit) for unit in packet["focus_units"]}
        kept = []
        actions = []
        raw_components = raw.get("components", [])
        raw_component_count += len(raw_components)

        for original in raw_components:
            component = deepcopy(original)
            component_id = component.get("component_id", "")
            members = {
                unit_key(member)
                for member in component.get("members", [])
                if isinstance(member, dict)
            }
            if not members & focus:
                actions.append(
                    {
                        "component_id": component_id,
                        "action": "dropped",
                        "reason": "component has no exact focus member",
                    }
                )
                continue

            contract = component.get("protocol_contract")
            consumers = contract.get("consumers") if isinstance(contract, dict) else None
            evidence_files = {
                item.get("file_id")
                for item in component.get("evidence", [])
                if isinstance(item, dict)
            }
            removed_consumers = []
            if isinstance(consumers, list):
                retained_consumers = []
                for consumer in consumers:
                    file_id = consumer.get("file_id") if isinstance(consumer, dict) else None
                    if file_id in evidence_files:
                        retained_consumers.append(consumer)
                    else:
                        removed_consumers.append(consumer)
                contract["consumers"] = retained_consumers

            validation = validate_protocol_contracts(
                {"components": [component]},
                packet=packet,
                repository_root=repository_root,
                schema_path=schema_path,
            )
            if validation["status"] != "ok":
                actions.append(
                    {
                        "component_id": component_id,
                        "action": "dropped",
                        "reason": "component remains invalid after evidence-backed consumer narrowing",
                        "removed_consumers": removed_consumers,
                        "validation_errors": validation["errors"],
                    }
                )
                continue

            if component_id in seen_ids:
                actions.append(
                    {
                        "component_id": component_id,
                        "action": "dropped",
                        "reason": "duplicate component ID; first valid occurrence retained",
                        "removed_consumers": removed_consumers,
                    }
                )
                continue

            seen_ids.add(component_id)
            retained_ids.append(component_id)
            kept.append(component)
            actions.append(
                {
                    "component_id": component_id,
                    "action": (
                        "retained_with_consumer_narrowing"
                        if removed_consumers
                        else "retained_unchanged"
                    ),
                    "removed_consumers": removed_consumers,
                }
            )

        if not kept:
            excluded_packets.append(
                {
                    "packet_id": packet_id,
                    "raw_response": str(raw_path.relative_to(PROJECT)),
                    "raw_response_sha256": sha256(raw_path),
                    "raw_component_count": len(raw_components),
                    "retained_component_count": 0,
                    "actions": actions,
                    "reason": "packet has no components after component-level admission",
                }
            )
            continue

        curated = deepcopy(raw)
        curated["components"] = kept
        if len(kept) != len(raw_components):
            curated["reason"] = (
                f"{len(kept)} of {len(raw_components)} raw components passed "
                "the deterministic component-level admission gate."
            )
        validation = validate_protocol_contracts(
            curated,
            packet=packet,
            repository_root=repository_root,
            schema_path=schema_path,
        )
        if validation["status"] != "ok":
            raise RuntimeError(f"curated packet remains invalid: {packet_id}")

        packet_root = curated_root / "packets" / packet_id
        response_path = packet_root / "extraction_response.json"
        validation_path = packet_root / "protocol_contract_validation.json"
        write_json(response_path, curated)
        write_json(validation_path, validation)
        packet_reports.append(
            {
                "packet_id": packet_id,
                "raw_response": str(raw_path.relative_to(PROJECT)),
                "raw_response_sha256": sha256(raw_path),
                "curated_response": str(response_path.relative_to(PROJECT)),
                "curated_response_sha256": sha256(response_path),
                "raw_component_count": len(raw_components),
                "retained_component_count": len(kept),
                "actions": actions,
                "validation": validation,
            }
        )

    report = {
        "schema": "ffsim-component-level-extraction-admission-v2",
        "task_blind": True,
        "task_id": config["task_id"],
        "policy": {
            "packet_atomic_rejection": False,
            "drop_context_only_components": True,
            "consumer_claims_require_evidence_file": True,
            "minimum_consumer_count": 2,
            "duplicate_component_ids": "retain_first_valid_occurrence",
            "add_new_evidence": False,
            "modify_library_code": False,
        },
        "raw_extraction_status": raw_summary.get("status"),
        "raw_summary": str(raw_summary_path.relative_to(PROJECT)),
        "raw_summary_sha256": sha256(raw_summary_path),
        "raw_packet_count": len(raw_summary["packet_ids"]),
        "retained_packet_count": len(packet_reports),
        "excluded_packet_count": len(excluded_packets),
        "raw_component_count": raw_component_count,
        "retained_component_count": len(retained_ids),
        "retained_component_ids": retained_ids,
        "packets": packet_reports,
        "excluded_packets": excluded_packets,
        "status": "completed",
    }
    write_json(summary_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
