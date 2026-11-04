#!/usr/bin/env python3
"""应用单次审核给出的协议字段修订，不再次调用审核模型。"""

from __future__ import annotations

from copy import deepcopy
import json

from component_method.workflow.experiment_common import (
    PROJECT,
    ROOT,
    load_json,
    validate_protocol_contracts,
    write_json,
)
from component_method.component_build.validation import materialize_protocol_contract_revision


FINAL_STATUS = "revisions_applied_without_rereview"


def main() -> None:
    config = load_json(ROOT / "config.json")
    if not config.get("apply_review_revisions_without_rereview"):
        raise RuntimeError("config does not authorize single-review local finalization")

    frozen = load_json(ROOT / "inputs" / "frozen_components.json")
    records = {record["component_id"]: record for record in frozen["records"]}
    packets_payload = load_json(ROOT / "inputs" / "focus_context_packets.json")
    packets = {packet["packet_id"]: packet for packet in packets_payload["packets"]}
    repository_root = PROJECT / config["repository_root"]
    schema_path = PROJECT / config["protocol_contract_schema"]
    review_root = ROOT / "runs" / config["task_id"] / "review_v1"
    summary_path = review_root / "summary.json"
    summary = load_json(summary_path)
    if summary.get("status") != "completed":
        raise RuntimeError("review is not complete")

    finalized = []
    for component_id in list(summary.get("withheld_components", [])):
        record = records[component_id]
        component_root = review_root / "components" / component_id
        initial = load_json(component_root / "initial_review.json")
        protocol_review = initial.get("protocol_contract_review", {})
        if protocol_review.get("status") != "needs_revision":
            raise RuntimeError(f"withheld component has no review revisions: {component_id}")

        blocking_fields = {
            issue["field"]
            for issue in protocol_review.get("field_issues", [])
            if isinstance(issue, dict) and issue.get("severity") == "blocking"
        }
        revisions = protocol_review.get("field_revisions")
        if not blocking_fields or not isinstance(revisions, dict):
            raise RuntimeError(f"review lacks complete blocking-field revisions: {component_id}")
        if set(revisions) != blocking_fields:
            raise RuntimeError(
                f"review revisions do not exactly cover blocking fields: {component_id}"
            )

        effective = deepcopy(record["component"])
        effective["protocol_contract"] = materialize_protocol_contract_revision(
            effective["protocol_contract"], protocol_review
        )
        validation = validate_protocol_contracts(
            {"components": [effective]},
            packet=packets[record["source_packet_id"]],
            repository_root=repository_root,
            schema_path=schema_path,
        )
        if validation.get("status") != "ok":
            raise RuntimeError(f"locally revised protocol contract is invalid: {component_id}")

        original_protocol_review = deepcopy(protocol_review)
        final_review = deepcopy(initial)
        final_review["status"] = "confirmed_after_local_revision"
        final_review["original_protocol_contract_review"] = original_protocol_review
        final_review["protocol_contract_review"] = {
            "schema_version": 2,
            "status": FINAL_STATUS,
            "source_review_status": original_protocol_review["status"],
            "reviewed_fields": sorted(blocking_fields),
            "confirmed_fields": [],
            "field_issues": [],
            "field_revisions": revisions,
        }
        final_review["single_review_finalization"] = {
            "model_calls_added": 0,
            "rereview_performed": False,
            "policy": FINAL_STATUS,
            "locally_validated": True,
            "validation_file": "local_revision_validation.json",
        }

        write_json(component_root / "effective_component.json", effective)
        write_json(component_root / "final_review.json", final_review)
        write_json(component_root / "local_revision_validation.json", validation)

        result_path = component_root / "result.json"
        result = load_json(result_path)
        result.update(
            repair_applied=True,
            repair_rounds=1,
            rereviewed_fields=[],
            local_revision_only=True,
            publication_basis=FINAL_STATUS,
            final={
                "component_review_status": final_review["status"],
                "artifact_review_status": final_review.get("artifact_review", {}).get("status"),
                "protocol_status": FINAL_STATUS,
                "blocking_fields": [],
                "warning_fields": [],
                "field_issues": [],
                "resolved_blocking_fields": sorted(blocking_fields),
                "blocks_publication": False,
            },
            publishable=True,
        )
        write_json(result_path, result)
        finalized.append(component_id)

    if not finalized:
        raise RuntimeError("no withheld component was eligible for local finalization")

    published = list(dict.fromkeys([*summary.get("published_components", []), *finalized]))
    summary["published_components"] = published
    summary["withheld_components"] = [
        component_id
        for component_id in summary.get("withheld_components", [])
        if component_id not in finalized
    ]
    summary["single_review_finalization"] = {
        "policy": FINAL_STATUS,
        "components": finalized,
        "model_calls_added": 0,
        "rereview_performed": False,
    }
    results = {result["component_id"]: result for result in summary["results"]}
    for component_id in finalized:
        results[component_id] = load_json(
            review_root / "components" / component_id / "result.json"
        )
    summary["results"] = [results[component_id] for component_id in summary["component_ids"]]
    write_json(summary_path, summary)
    write_json(review_root / "run_manifest.json", summary)
    print(
        json.dumps(
            {
                "status": "completed",
                "finalized_components": finalized,
                "model_calls_added": 0,
                "rereview_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
