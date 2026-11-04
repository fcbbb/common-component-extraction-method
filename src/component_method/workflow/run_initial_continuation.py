#!/usr/bin/env python3
"""Continue the revised pipeline from first-pass extraction artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from component_method.workflow.batch_common import (
    PROJECT,
    ROOT,
    admit_review_component_failures,
    archive_failed_review_outputs,
    config,
    load_json,
    tasks,
    write_json,
)


STAGES = ("curate", "prepare_reviews", "review", "publish", "retrieval", "task")


def task_record(task_id: str) -> dict[str, Any]:
    try:
        return next(task for task in tasks() if task["instance_id"] == task_id)
    except StopIteration as exc:
        raise RuntimeError(f"unknown task: {task_id}") from exc


def pipeline_python(task: dict[str, Any]) -> Path:
    return Path(sys.executable)


def completed(root: Path, task_id: str, stage: str) -> bool:
    paths = {
        "curate": root / "runs" / task_id / "extraction_v1" / "curated" / "summary.json",
        "prepare_reviews": root / "inputs" / "frozen_components.json",
        "review": root / "runs" / task_id / "review_v1" / "summary.json",
        "publish": root / "outputs" / "full_library" / "manifest.json",
        "retrieval": root / "attempts" / "retrieval_01" / "metadata.json",
        "task": root / "task_attempts" / "task_01" / "run_manifest.json",
    }
    path = paths[stage]
    if not path.is_file():
        return False
    if stage in {"curate", "review", "task"}:
        return load_json(path).get("status") == "completed"
    return True


def run_stage(
    task: dict[str, Any],
    root: Path,
    stage: str,
    *,
    resume: bool,
    review_workers: int,
) -> None:
    task_id = task["instance_id"]
    if stage == "review" and resume:
        admission = admit_review_component_failures(root, task_id)
        if admission is not None:
            print(
                f"[continuation] quarantined "
                f"{len(admission['quarantined_components'])} failed review components "
                f"for {task_id}",
                flush=True,
            )
    if resume and completed(root, task_id, stage):
        print(f"[continuation] skip {task_id} {stage}", flush=True)
        return
    if stage == "review" and resume:
        archived = archive_failed_review_outputs(root, task_id)
        if archived is not None:
            print(
                f"[continuation] archived {len(archived['archived'])} failed review "
                f"outputs for {task_id}",
                flush=True,
            )
    command = [
        str(pipeline_python(task)),
        "-m",
        "component_method.workflow.run_stage",
        "--task-root",
        str(root),
        "--stage",
        stage,
    ]
    if stage == "review":
        if resume:
            command.append("--resume")
        command.extend(("--workers", str(review_workers)))
    env = os.environ.copy()
    cfg = config()
    env["MODEL_NAME"] = cfg["model"]
    env["OPENAI_API_BASE"] = cfg["api_base"]
    print(f"[continuation] start {task_id} {stage}", flush=True)
    result = subprocess.run(command, cwd=PROJECT, env=env, check=False)
    if result.returncode:
        if stage == "review":
            admission = admit_review_component_failures(root, task_id)
            if admission is not None:
                print(
                    f"[continuation] accept {task_id} review with "
                    f"{len(admission['quarantined_components'])} quarantined components",
                    flush=True,
                )
            else:
                result.check_returncode()
        else:
            result.check_returncode()
    print(f"[continuation] done {task_id} {stage}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", required=True)
    parser.add_argument("--name", default="initial_admission")
    parser.add_argument("--from-stage", choices=STAGES, default="review")
    parser.add_argument("--through-stage", choices=STAGES, default="task")
    parser.add_argument("--review-workers", type=int, default=config()["pipeline"]["review_workers"])
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.set_defaults(resume=True)
    args = parser.parse_args()

    first = STAGES.index(args.from_stage)
    last = STAGES.index(args.through_stage)
    if first > last:
        raise RuntimeError("--from-stage must not come after --through-stage")

    failures = []
    for task_id in args.task:
        task = task_record(task_id)
        root = ROOT / "tasks" / task_id / "continuations" / args.name
        if not root.joinpath("continuation.json").is_file():
            raise RuntimeError(
                f"continuation is not prepared: {root}; run prepare_initial_continuation.py first"
            )
        state_path = root / "continuation_state.json"
        previous = load_json(state_path) if state_path.is_file() else {}
        state = {
            "task_id": task_id,
            "continuation": args.name,
            "status": "running",
            "extraction_model_rerun": False,
            "stages": previous.get("stages", {}),
            "started_at_unix": previous.get("started_at_unix", time.time()),
            "updated_at_unix": time.time(),
        }
        write_json(state_path, state)
        try:
            for stage in STAGES[first : last + 1]:
                run_stage(
                    task,
                    root,
                    stage,
                    resume=args.resume,
                    review_workers=args.review_workers,
                )
                state["stages"][stage] = "completed"
                write_json(state_path, state)
            state["status"] = "completed"
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = repr(exc)
            failures.append({"task_id": task_id, "error": repr(exc)})
        state["finished_at_unix"] = time.time()
        state["updated_at_unix"] = state["finished_at_unix"]
        write_json(state_path, state)

    print(json.dumps({"failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
