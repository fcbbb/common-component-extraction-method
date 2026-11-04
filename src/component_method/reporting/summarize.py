#!/usr/bin/env python3
"""Summarize imported direct baselines and imported/new component runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from component_method.workflow.batch_common import ROOT, completed_component_manifest, tasks, write_json


def read(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def evaluation_from_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    evaluation = result.get("evaluation")
    if isinstance(evaluation, dict):
        return evaluation
    return result


def main() -> int:
    rows = []
    for task in tasks():
        instance_id = task["instance_id"]
        direct = read(
            ROOT / "imports" / "direct" / instance_id / "outputs" / "tasks" / "direct" / instance_id / "evaluation" / "result.json"
        )
        component_path = completed_component_manifest(instance_id)
        component = read(component_path) if component_path else None
        if task["component_status"] == "imported_pilot":
            component = read(
                ROOT / "imports" / "component_pilots" / instance_id / "task_attempts" / "task_01" / "run_manifest.json"
            ) or read(
                ROOT / "imports" / "component_pilots" / instance_id / "downstream_task" / "attempts" / "task_attempt_07" / "run_manifest.json"
            )
        rows.append(
            {
                "instance_id": instance_id,
                "cohort": task["cohort"],
                "direct_status": task["direct_status"],
                "component_status": (
                    component.get("status") if component else task["component_status"]
                ),
                "direct_evaluation": evaluation_from_result(direct),
                "component_evaluation": component.get("evaluation") if component else None,
                "comparison_eligible": (
                    task["cohort"] == "primary"
                    and task["direct_status"] == "completed"
                    and component is not None
                    and component.get("status") == "completed"
                ),
                "pilot_result": task["component_status"] == "imported_pilot",
            }
        )
    payload = {
        "schema": "frozen-component-batch-summary-v1",
        "counts": {
            "tasks": len(rows),
            "primary": sum(row["cohort"] == "primary" for row in rows),
            "reserve": sum(row["cohort"] == "reserve" for row in rows),
            "comparison_eligible": sum(row["comparison_eligible"] for row in rows),
            "imported_pilots": sum(row["pilot_result"] for row in rows),
        },
        "tasks": rows,
    }
    write_json(ROOT / "summary.json", payload)
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
