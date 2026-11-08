#!/usr/bin/env python3
"""Batch the frozen component workflow without changing production pipeline code."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from component_method.agent_runtime import selected_backend_name
from component_method.workflow.batch_common import (
    PROJECT,
    ROOT,
    admit_review_component_failures,
    archive_failed_review_outputs,
    completed_component_manifest,
    config,
    load_json,
    repository_stats,
    select_tasks,
    sha256_file,
    sort_tasks_by_repository_size,
    write_json,
)


PIPELINE_STAGES = (
    "prepare",
    "extract",
    "curate",
    "prepare_reviews",
    "review",
    "publish",
    "retrieval",
    "task",
)

BASELINE_ENV_PACKAGES = (
    "openai",
    "docker",
    "httpx",
    "pydantic",
)


def completed(task: dict[str, Any], stage: str) -> bool:
    root = ROOT / "tasks" / task["instance_id"]
    instance_id = task["instance_id"]
    paths = {
        "prepare": root / "inputs" / "focus_context_packets.json",
        "extract": root / "runs" / instance_id / "extraction_v1" / "summary.json",
        "curate": root / "runs" / instance_id / "extraction_v1" / "curated" / "summary.json",
        "prepare_reviews": root / "inputs" / "frozen_components.json",
        "review": root / "runs" / instance_id / "review_v1" / "summary.json",
        "publish": root / "outputs" / "full_library" / "manifest.json",
        "retrieval": root / "attempts" / "retrieval_01" / "metadata.json",
        "task": root / "task_attempts" / "task_01" / "run_manifest.json",
    }
    if stage == "task":
        return completed_component_manifest(instance_id) is not None
    path = paths[stage]
    if not path.is_file():
        return False
    if stage == "extract":
        return extraction_ready_for_admission(load_json(path))
    if stage in {"curate", "review"}:
        return load_json(path).get("status") == "completed"
    return True


def extraction_ready_for_admission(summary: dict[str, Any]) -> bool:
    """Return whether extraction finished without execution/runtime failures."""
    packet_ids = summary.get("packet_ids")
    results = summary.get("results")
    if not isinstance(packet_ids, list) or not isinstance(results, list):
        return False
    if len(results) != len(packet_ids):
        return False
    result_ids = {result.get("packet_id") for result in results}
    if result_ids != set(packet_ids):
        return False
    return all(result.get("status") in {"ok", "invalid_contract"} for result in results)


def materialize_config(task: dict[str, Any]) -> None:
    root = ROOT / "tasks" / task["instance_id"]
    candidate = root / "candidates" / "protocol_candidates_v2.json"
    if not candidate.is_file():
        raise RuntimeError(f"candidate file missing for {task['instance_id']}: {candidate}")
    payload = load_json(root / "pipeline_config.template.json")
    payload["candidate_sha256"] = sha256_file(candidate)
    write_json(root / "config.json", payload)


def pipeline_python(task: dict[str, Any], args: argparse.Namespace) -> Path:
    if args.pipeline_python is not None:
        python = args.pipeline_python.absolute()
    else:
        python = Path(sys.executable).absolute()
    if not python.is_file():
        raise RuntimeError(
            f"baseline Python missing for {task['instance_id']}: {python}"
        )
    return python


def environment_identity(python: Path) -> dict[str, Any]:
    agent_backend = selected_backend_name()
    packages = list(BASELINE_ENV_PACKAGES)
    script = (
        "import importlib.metadata as m,json,sys;"
        f"names={packages!r};"
        "print(json.dumps({'executable':sys.executable,'version':sys.version,"
        "'packages':{name:m.version(name) for name in names}},sort_keys=True))"
    )
    result = subprocess.run(
        [str(python), "-c", script],
        cwd=PROJECT,
        check=True,
        capture_output=True,
        text=True,
    )
    identity = {**json.loads(result.stdout), "agent_backend": agent_backend}
    from component_method.agent_runtime import BackendSettings, create_agent_backend

    identity["agent_runtime"] = create_agent_backend(
        BackendSettings(api_key="identity-only", base_url="identity-only"),
        name=agent_backend,
    ).runtime_identity()
    return identity


def run_stage(task: dict[str, Any], stage: str, args: argparse.Namespace) -> None:
    if stage == "review" and args.resume:
        admission = admit_review_component_failures(
            ROOT / "tasks" / task["instance_id"],
            task["instance_id"],
        )
        if admission is not None:
            print(
                f"[pipeline] quarantined "
                f"{len(admission['quarantined_components'])} failed review components "
                f"for {task['instance_id']}",
                flush=True,
            )
    if args.resume and completed(task, stage):
        print(f"[pipeline] skip {task['instance_id']} {stage}", flush=True)
        return
    if stage == "review" and args.resume:
        archived = archive_failed_review_outputs(
            ROOT / "tasks" / task["instance_id"],
            task["instance_id"],
        )
        if archived is not None:
            print(
                f"[pipeline] archived {len(archived['archived'])} failed review "
                f"outputs for {task['instance_id']}",
                flush=True,
            )
    command = [
        str(pipeline_python(task, args)),
        "-m",
        "component_method.workflow.run_stage",
        "--task-root",
        str(ROOT / "tasks" / task["instance_id"]),
        "--stage",
        stage,
    ]
    if stage == "extract":
        if args.resume:
            command.append("--resume")
        command.extend(("--workers", str(args.extraction_workers)))
    elif stage == "review":
        if args.resume:
            command.append("--resume")
        command.extend(("--workers", str(args.review_workers)))
    env = os.environ.copy()
    cfg = config()
    env["MODEL_NAME"] = cfg["model"]
    env["OPENAI_API_BASE"] = cfg["api_base"]
    env["AGENT_BACKEND"] = selected_backend_name(env)
    print(f"[pipeline] start {task['instance_id']} {stage}", flush=True)
    result = subprocess.run(command, cwd=PROJECT, env=env, check=False)
    if result.returncode:
        if stage == "extract":
            summary_path = (
                ROOT
                / "tasks"
                / task["instance_id"]
                / "runs"
                / task["instance_id"]
                / "extraction_v1"
                / "summary.json"
            )
            if summary_path.is_file() and extraction_ready_for_admission(
                load_json(summary_path)
            ):
                print(
                    f"[pipeline] accept {task['instance_id']} extract with "
                    "component-level contract rejections",
                    flush=True,
                )
            else:
                result.check_returncode()
        elif stage == "review":
            admission = admit_review_component_failures(
                ROOT / "tasks" / task["instance_id"],
                task["instance_id"],
            )
            if admission is not None:
                print(
                    f"[pipeline] accept {task['instance_id']} review with "
                    f"{len(admission['quarantined_components'])} quarantined components",
                    flush=True,
                )
            else:
                result.check_returncode()
        else:
            result.check_returncode()
    print(f"[pipeline] done {task['instance_id']} {stage}", flush=True)


def run_pipeline(task: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    state_path = ROOT / "tasks" / task["instance_id"] / "batch_state.json"
    python = pipeline_python(task, args)
    state = {
        "instance_id": task["instance_id"],
        "status": "running",
        "frozen_pipeline": config()["frozen_pipeline"],
        "pipeline_environment": environment_identity(python),
        "pipeline_environment_source": (
            "explicit_override"
            if args.pipeline_python is not None
            else "current_release_environment"
        ),
        "stages": {},
    }
    write_json(state_path, state)
    try:
        materialize_config(task)
        for stage in PIPELINE_STAGES:
            run_stage(task, stage, args)
            state["stages"][stage] = "completed"
            write_json(state_path, state)
        state["status"] = "completed"
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = repr(exc)
        write_json(state_path, state)
        raise
    state["elapsed_seconds"] = round(time.monotonic() - started, 2)
    write_json(state_path, state)
    return state


def run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=(
            "prepare-embeddings",
            "compute-embeddings",
            "candidates",
            "pipeline",
            "remaining",
            "all",
        ),
        default="pipeline",
        help=(
            "Use 'remaining' after embeddings are available to build missing "
            "candidates and run only unfinished component tasks."
        ),
    )
    parser.add_argument("--task", action="append")
    parser.add_argument("--include-reserve", action="store_true")
    parser.add_argument("--include-no-direct", action="store_true")
    parser.add_argument("--rerun-imported-pilots", action="store_true")
    parser.add_argument("--task-workers", type=int, default=1)
    parser.add_argument(
        "--task-order",
        choices=("small-first", "manifest"),
        default="small-first",
        help=(
            "Run smaller frozen repository snapshots first (default), or keep "
            "the selected order (tasks.json by default, explicit --task order "
            "when supplied). Explicit --task arguments are also reordered unless "
            "--task-order manifest is used."
        ),
    )
    parser.add_argument(
        "--embedding-python",
        type=Path,
        default=Path(sys.executable),
    )
    parser.add_argument(
        "--pipeline-python",
        type=Path,
        default=None,
        help=(
            "Override the Python executable used for the release pipeline. "
            "By default the current environment is used."
        ),
    )
    parser.add_argument("--extraction-workers", type=int, default=None)
    parser.add_argument("--review-workers", type=int, default=None)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.set_defaults(resume=True)
    args = parser.parse_args()
    cfg = config()
    if args.extraction_workers is None:
        args.extraction_workers = cfg["pipeline"]["extraction_workers"]
    if args.review_workers is None:
        args.review_workers = cfg["pipeline"]["review_workers"]
    selected = select_tasks(
        args.task,
        include_reserve=args.include_reserve,
        require_direct=not args.include_no_direct and not args.task,
    )
    runnable = []
    skipped_completed = []
    for task in selected:
        if task["cohort"] == "reserve":
            continue
        if task["component_status"] == "imported_pilot" and not args.rerun_imported_pilots:
            continue
        if args.resume and completed(task, "task"):
            skipped_completed.append(task)
            continue
        runnable.append(task)
    if args.task_order == "small-first":
        runnable = sort_tasks_by_repository_size(runnable)
    size_stats = repository_stats()
    if runnable:
        print(f"[pipeline] task order: {args.task_order}", flush=True)
        for number, task in enumerate(runnable, 1):
            stats = size_stats.get(task["instance_id"], {})
            print(
                f"[pipeline] order {number:02d}: {task['instance_id']} "
                f"units={stats.get('units', 'unknown')} "
                f"source_bytes={stats.get('source_bytes', 'unknown')} "
                f"files={stats.get('eligible_files', 'unknown')}",
                flush=True,
            )
    # Preserve the virtual-environment launcher path. Path.resolve() follows the
    # bin/python symlink to /usr/bin/python and drops the venv site-packages.
    embedding_python = str(args.embedding_python.absolute())
    if args.stage in {"prepare-embeddings", "all"}:
        command = [sys.executable, "-m", "component_method.signal_analysis.prepare_embeddings"]
        for task_id in args.task or []:
            command.extend(("--task", task_id))
        run_command(command)
    if args.stage in {"compute-embeddings", "all"}:
        command = [embedding_python, "-m", "component_method.signal_analysis.compute_embeddings"]
        if args.resume:
            command.append("--resume")
        run_command(command)
    if args.stage in {"candidates", "remaining", "all"}:
        command = [embedding_python, "-m", "component_method.protocol_candidates.build_candidates"]
        candidate_tasks = runnable if args.stage in {"remaining", "all"} else selected
        if args.task_order == "small-first":
            candidate_tasks = sort_tasks_by_repository_size(candidate_tasks)
        for task in candidate_tasks:
            command.extend(("--task", task["instance_id"]))
        if args.include_reserve:
            command.append("--include-reserve")
        if args.resume:
            command.append("--resume")
        if candidate_tasks:
            run_command(command)
        else:
            print("[candidate] no unfinished tasks selected", flush=True)
    if args.stage not in {"pipeline", "remaining", "all"}:
        return 0
    for task in selected:
        if task["cohort"] == "reserve":
            print(f"[pipeline] reserve remains embedding-only: {task['instance_id']}", flush=True)
            continue
        if task["component_status"] == "imported_pilot" and not args.rerun_imported_pilots:
            print(f"[pipeline] imported pilot preserved: {task['instance_id']}", flush=True)
            continue
        if task in skipped_completed:
            manifest = completed_component_manifest(task["instance_id"])
            print(
                f"[pipeline] completed result preserved: {task['instance_id']} "
                f"({manifest.relative_to(ROOT)})",
                flush=True,
            )
    if not runnable:
        print("[pipeline] no tasks selected", flush=True)
        run_command([sys.executable, "-m", "component_method.reporting.summarize"])
        return 0
    failures = []
    with ThreadPoolExecutor(max_workers=args.task_workers) as executor:
        futures = {executor.submit(run_pipeline, task, args): task for task in runnable}
        for future in as_completed(futures):
            task = futures[future]
            try:
                future.result()
            except Exception as exc:
                failures.append({"instance_id": task["instance_id"], "error": repr(exc)})
                print(f"[pipeline] failed {task['instance_id']}: {exc!r}", flush=True)
    write_json(
        ROOT / "batch_run_summary.json",
        {
            "task_order": args.task_order,
            "selected": [task["instance_id"] for task in runnable],
            "selected_repository_sizes": [
                {
                    "instance_id": task["instance_id"],
                    "units": size_stats.get(task["instance_id"], {}).get("units"),
                    "source_bytes": size_stats.get(task["instance_id"], {}).get(
                        "source_bytes"
                    ),
                    "eligible_files": size_stats.get(task["instance_id"], {}).get(
                        "eligible_files"
                    ),
                }
                for task in runnable
            ],
            "completed": [
                task["instance_id"]
                for task in runnable
                if completed(task, "task")
            ],
            "failures": failures,
        },
    )
    run_command([sys.executable, str(ROOT / "summarize.py")])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
