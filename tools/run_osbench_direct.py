#!/usr/bin/env python3
"""Run the prepared OS-Bench direct baselines and their official evaluation.

This runner deliberately separates agent execution from evaluation.  The agent
uses the prepared direct task root and the pinned Node/DSH runtime; evaluation
uses the OS-Bench rebuild/test/print adapter and never calls a model.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
DEFAULT_WORKSPACE = REPOSITORY / "work" / "osbench"
DEFAULT_OUTPUT = DEFAULT_WORKSPACE / "direct_baseline"
NODE_BIN = Path.home() / ".nvm" / "versions" / "node" / "v24.9.0" / "bin" / "node"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def selected_ids(workspace: Path, requested: list[str] | None) -> list[str]:
    rows = read_json(workspace / "tasks.json")["tasks"]
    available = [row["instance_id"] for row in rows]
    if not requested:
        return available
    missing = sorted(set(requested) - set(available))
    if missing:
        raise RuntimeError(f"unknown OS-Bench task IDs: {missing}")
    return list(dict.fromkeys(requested))


def task_root(output_root: Path, instance_id: str) -> Path:
    root = output_root / instance_id
    if not (root / "run_direct.sh").is_file():
        raise RuntimeError(f"direct baseline is not prepared: {root}")
    return root


def agent_result(root: Path, instance_id: str) -> Path:
    return root / "outputs" / "tasks" / "direct" / instance_id / "result.json"


def evaluation_result(root: Path, instance_id: str) -> Path:
    return root / "outputs" / "tasks" / "direct" / instance_id / "evaluation" / "result.json"


def run_agent(root: Path, instance_id: str, timeout: int) -> dict[str, Any]:
    log_path = root / "agent_run.log"
    environment = os.environ.copy()
    environment["PATH"] = f"{NODE_BIN.parent}:{environment.get('PATH', '')}"
    environment["COMPONENT_DSH_NODE_BIN"] = str(NODE_BIN)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            ["bash", str(root / "run_direct.sh")],
            cwd=REPOSITORY,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    if completed.returncode:
        raise RuntimeError(f"direct agent runner exited {completed.returncode}; see {log_path}")
    result_path = agent_result(root, instance_id)
    if not result_path.is_file():
        raise RuntimeError(f"direct agent produced no result: {result_path}")
    return read_json(result_path)


def evaluate(root: Path, instance_id: str, timeout: int) -> dict[str, Any]:
    result_path = agent_result(root, instance_id)
    result = read_json(result_path)
    output = root / "outputs" / "tasks" / "direct" / instance_id / "evaluation"
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "COMPONENT_METHOD_RELEASE_ROOT": str(root.parent.parent),
            "COMPONENT_METHOD_TASK_ROOT": str(root),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPOSITORY / "src"),
                    str(REPOSITORY / "src" / "component_method" / "task_execution" / "core"),
                    str(REPOSITORY / "src" / "component_method" / "task_execution" / "adapters"),
                ]
            ),
        }
    )
    script = """
import json
from pathlib import Path
import sys
import common, evaluation
result = json.loads(Path(sys.argv[1]).read_text())
official = common.rows()[0]
out = Path(sys.argv[2])
if result.get("patch_available") and result.get("patch"):
    value = evaluation.evaluate(official, result["patch"], out)
else:
    value = evaluation.not_evaluated(official, out, result.get("error") or "no patch")
print(json.dumps(value, ensure_ascii=False))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(result_path), str(output)],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    (output / "evaluator.log").write_text(
        completed.stdout + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode:
        raise RuntimeError(
            f"OS-Bench evaluation exited {completed.returncode}; see {output / 'evaluator.log'}"
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--task", action="append", help="OS-Bench task ID; repeatable.")
    parser.add_argument("--skip-completed", action="store_true", help="Skip tasks with an evaluation result.")
    parser.add_argument("--evaluate-only", action="store_true", help="Do not run the agent.")
    parser.add_argument("--agent-timeout", type=int, default=7200)
    parser.add_argument("--evaluation-timeout", type=int, default=3600)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output_root = args.output_root.resolve()
    summaries = []
    for instance_id in selected_ids(workspace, args.task):
        root = task_root(output_root, instance_id)
        evaluation_path = evaluation_result(root, instance_id)
        if args.skip_completed and evaluation_path.is_file():
            summaries.append(
                {
                    "instance_id": instance_id,
                    "status": "skipped_completed",
                    "agent_result": str(agent_result(root, instance_id)),
                    "evaluation_result": str(evaluation_path),
                }
            )
            continue
        agent = read_json(agent_result(root, instance_id)) if (agent_result(root, instance_id)).is_file() else None
        if not args.evaluate_only:
            print(f"[direct] agent {instance_id}", flush=True)
            agent = run_agent(root, instance_id, args.agent_timeout)
        if agent is None:
            raise RuntimeError(f"missing direct agent result for {instance_id}")
        print(f"[direct] evaluate {instance_id}", flush=True)
        evaluation = evaluate(root, instance_id, args.evaluation_timeout)
        summaries.append(
            {
                "instance_id": instance_id,
                "status": agent.get("status"),
                "patch_available": bool(agent.get("patch_available")),
                "model_calls": agent.get("model_calls"),
                "elapsed_seconds": agent.get("elapsed_seconds"),
                "agent_result": str(agent_result(root, instance_id)),
                "evaluation": evaluation,
            }
        )
        write_json(
            output_root / "results_summary.json",
            {
                "schema": "osbench-direct-results-v1",
                "tasks": summaries,
            },
        )
    write_json(
        output_root / "results_summary.json",
        {
            "schema": "osbench-direct-results-v1",
            "tasks": summaries,
        },
    )
    print(json.dumps({"tasks": len(summaries), "summary": str(output_root / 'results_summary.json')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())