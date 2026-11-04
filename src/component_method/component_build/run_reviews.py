#!/usr/bin/env python3
"""Run audit gate v2 with at most one field-only repair per FFSIM component."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json, sha256, write_json

from component_method.component_build.extraction.runner import (  # noqa: E402
    OfficialImageExtractionRunner,
)
from component_method.component_build.validation import (  # noqa: E402
    materialize_protocol_contract_revision,
    protocol_review_blocks_publication,
    review_component_with_agent,
)


def protocol_summary(review: dict) -> dict:
    protocol = review["protocol_contract_review"]
    issues = protocol.get("field_issues", [])
    return {
        "component_review_status": review.get("status"),
        "artifact_review_status": review.get("artifact_review", {}).get("status"),
        "protocol_status": protocol.get("status"),
        "blocking_fields": sorted(
            {
                issue["field"]
                for issue in issues
                if isinstance(issue, dict) and issue.get("severity") == "blocking"
            }
        ),
        "warning_fields": sorted(
            {
                issue["field"]
                for issue in issues
                if isinstance(issue, dict) and issue.get("severity") == "warning"
            }
        ),
        "field_issues": issues,
        "blocks_publication": protocol_review_blocks_publication(protocol),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    config = load_json(ROOT / "config.json")
    if os.environ.get("MODEL_NAME") != config["model"]:
        raise RuntimeError(f"MODEL_NAME must be {config['model']}")
    if os.environ.get("OPENAI_API_BASE", "").rstrip("/") != config["api_base"]:
        raise RuntimeError(f"OPENAI_API_BASE must be {config['api_base']}")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    frozen_path = ROOT / "inputs" / "frozen_components.json"
    frozen = load_json(frozen_path)
    for source in frozen["source_responses"]:
        if sha256(PROJECT / source["path"]) != source["sha256"]:
            raise RuntimeError(f"frozen extraction response changed: {source['path']}")

    repository_root = PROJECT / config["repository_root"]
    runner = OfficialImageExtractionRunner(
        model=config["model"],
        api_key=api_key,
        base_url=config["api_base"],
        timeout_seconds=config["agent_timeout_seconds"],
        runtime_image=config["runtime_image"],
        repository_root=repository_root,
    )
    workers = args.workers or config["review_workers"]
    run_root = ROOT / "runs" / config["task_id"] / "review_v1"
    manifest_path = run_root / "run_manifest.json"
    manifest = {
        "schema": "ffsim-audit-gate-v2-run-v1",
        "task_blind": True,
        "task_information_used": False,
        "task_id": config["task_id"],
        "component_ids": frozen["component_ids"],
        "component_count": frozen["component_count"],
        "workers": workers,
        "max_repair_rounds": config["max_review_repair_rounds"],
        "repair_mode": "apply_reviewer_field_revisions",
        "rereview_mode": "changed_fields_only",
        "model": config["model"],
        "runtime_image": config["runtime_image"],
        "frozen_inputs_sha256": sha256(frozen_path),
    }
    if manifest_path.exists():
        existing = load_json(manifest_path)
        for key in ("task_id", "component_ids", "frozen_inputs_sha256", "model"):
            if existing.get(key) != manifest[key]:
                raise RuntimeError(f"existing review manifest changed at {key}")
        if not args.resume:
            raise RuntimeError("review already started; use --resume")
    else:
        write_json(manifest_path, {**manifest, "status": "running"})

    def review_one(record: dict) -> tuple[str, dict]:
        component_id = record["component_id"]
        component_root = run_root / "components" / component_id
        result_path = component_root / "result.json"
        if result_path.is_file():
            previous = load_json(result_path)
            if previous.get("status") == "ok":
                return component_id, {**previous, "resumed": True}
        if component_root.exists() and any(component_root.iterdir()):
            raise RuntimeError(f"incomplete review output requires cleanup: {component_root}")

        component = deepcopy(record["component"])
        started = time.monotonic()
        try:
            payload = {
                "source_packet_id": record["source_packet_id"],
                "candidate": component,
                "proposed_component": component,
            }
            initial = review_component_with_agent(
                runner,
                repository_root,
                payload,
                component_root / "initial_review",
            )
            write_json(component_root / "initial_review.json", initial)
            initial_summary = protocol_summary(initial)
            final_review = initial
            effective_component = component
            repair_applied = False
            rereviewed_fields = []

            if (
                initial["protocol_contract_review"]["status"] == "needs_revision"
                and config["max_review_repair_rounds"] > 0
            ):
                blocking_fields = initial_summary["blocking_fields"]
                if not blocking_fields:
                    raise RuntimeError("needs_revision returned without blocking fields")
                effective_component = deepcopy(component)
                effective_component["protocol_contract"] = (
                    materialize_protocol_contract_revision(
                        component["protocol_contract"],
                        initial["protocol_contract_review"],
                    )
                )
                repair_applied = True
                rereviewed_fields = blocking_fields
                scoped_payload = {
                    "source_packet_id": record["source_packet_id"],
                    "candidate": effective_component,
                    "proposed_component": effective_component,
                    "protocol_review_scope": {
                        "fields": blocking_fields,
                        "previous_review": initial["protocol_contract_review"],
                    },
                }
                final_review = review_component_with_agent(
                    runner,
                    repository_root,
                    scoped_payload,
                    component_root / "scoped_rereview",
                )

            write_json(component_root / "effective_component.json", effective_component)
            write_json(component_root / "final_review.json", final_review)
            final_summary = protocol_summary(final_review)
            publishable = (
                final_review.get("status") == "confirmed"
                and final_review.get("artifact_review", {}).get("status") == "faithful"
                and not final_summary["blocks_publication"]
            )
            result = {
                "source_packet_id": record["source_packet_id"],
                "component_id": component_id,
                "status": "ok",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "repair_applied": repair_applied,
                "repair_rounds": 1 if repair_applied else 0,
                "rereviewed_fields": rereviewed_fields,
                "initial": initial_summary,
                "final": final_summary,
                "publishable": publishable,
            }
        except Exception as exc:
            result = {
                "source_packet_id": record["source_packet_id"],
                "component_id": component_id,
                "status": "failed",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
        write_json(result_path, result)
        return component_id, result

    results_by_id = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(review_one, record): record["component_id"]
            for record in frozen["records"]
        }
        for completed, future in enumerate(as_completed(futures), 1):
            component_id = futures[future]
            try:
                _, result = future.result()
            except Exception as exc:
                result = {
                    "component_id": component_id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            results_by_id[component_id] = result
            print(
                json.dumps(
                    {"completed": completed, "total": frozen["component_count"], **result},
                    ensure_ascii=False,
                ),
                flush=True,
            )

    results = [results_by_id[component_id] for component_id in frozen["component_ids"]]
    statuses = [load_json(path) for path in run_root.glob("components/**/agent_status.json")]
    summary = {
        **manifest,
        "status": "completed"
        if all(result["status"] == "ok" for result in results)
        else "failed",
        "successful_components": sum(result["status"] == "ok" for result in results),
        "failed_components": sum(result["status"] != "ok" for result in results),
        "published_components": [
            result["component_id"] for result in results if result.get("publishable")
        ],
        "withheld_components": [
            result["component_id"]
            for result in results
            if result["status"] == "ok" and not result.get("publishable")
        ],
        "results": results,
        "review_api_calls": sum(int(status.get("api_calls") or 0) for status in statuses),
        "review_reported_cost_usd": round(
            sum(float(status.get("reported_cost_usd") or 0) for status in statuses), 9
        ),
    }
    write_json(run_root / "summary.json", summary)
    write_json(manifest_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed_components"]:
        raise SystemExit(1)
    if not summary["published_components"]:
        raise RuntimeError("review produced no publishable components")


if __name__ == "__main__":
    main()
