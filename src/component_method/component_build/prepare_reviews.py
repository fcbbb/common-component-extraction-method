#!/usr/bin/env python3
"""Freeze all extracted FFSIM components for independent audit-gate review."""

from __future__ import annotations

import json

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json, sha256, write_json


def main() -> None:
    config = load_json(ROOT / "config.json")
    extraction_root = ROOT / "runs" / config["task_id"] / "extraction_v1"
    curated_root = extraction_root / "curated"
    summary = load_json(curated_root / "summary.json")
    if summary.get("status") != "completed":
        raise RuntimeError("curated extraction admission is not complete")

    records = []
    source_responses = []
    seen_ids = set()
    for packet_report in summary["packets"]:
        packet_id = packet_report["packet_id"]
        response_path = curated_root / "packets" / packet_id / "extraction_response.json"
        validation_path = (
            curated_root / "packets" / packet_id / "protocol_contract_validation.json"
        )
        validation = load_json(validation_path)
        if validation.get("status") != "ok":
            raise RuntimeError(f"packet contract validation failed: {packet_id}")
        response = load_json(response_path)
        source_responses.append(
            {
                "packet_id": packet_id,
                "path": str(response_path.relative_to(PROJECT)),
                "sha256": sha256(response_path),
            }
        )
        for component in response.get("components", []):
            component_id = component.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                raise RuntimeError(f"missing component ID in {packet_id}")
            if component_id in seen_ids:
                raise RuntimeError(f"duplicate component ID across packets: {component_id}")
            seen_ids.add(component_id)
            if component.get("status") != "draft_ready":
                raise RuntimeError(f"component is not draft_ready: {component_id}")
            records.append(
                {
                    "source_packet_id": packet_id,
                    "component_id": component_id,
                    "component": component,
                }
            )

    payload = {
        "schema": "ffsim-audit-gate-v2-input-v1",
        "task_blind": True,
        "task_id": config["task_id"],
        "source_extraction_summary": {
            "path": str((curated_root / "summary.json").relative_to(PROJECT)),
            "sha256": sha256(curated_root / "summary.json"),
        },
        "source_responses": source_responses,
        "component_count": len(records),
        "component_ids": [record["component_id"] for record in records],
        "records": records,
    }
    output = ROOT / "inputs" / "frozen_components.json"
    if output.exists() and load_json(output) != payload:
        raise RuntimeError(f"preserving different frozen review input: {output}")
    write_json(output, payload)
    print(
        json.dumps(
            {
                "output": str(output.relative_to(PROJECT)),
                "component_count": len(records),
                "component_ids": payload["component_ids"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
