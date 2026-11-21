#!/usr/bin/env python3
"""Run one atomic block of the component method in a task workspace.

Blocks are the only supported stage selection.  Retired sub-stage names
(``extract``, ``curate``, ``review`` …) still resolve to their owning block so
existing scripts keep working, but a block always runs as one unit unless
``--steps`` is used for debugging.

The block's prerequisites are checked before anything runs.  ``--check`` prints
the same decision without executing, which is what an agent should call when it
is not sure whether a requested piece of work is possible.
"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

from component_method.workflow import batch_common, experiment_common
from component_method.workflow.blocks import (
    BLOCKS,
    block_status,
    publish_mode,
    resolve_block,
    resolve_blocks,
    selected_from_config,
    step_artifact,
    step_enabled,
)


STEP_MODULES = {
    "source_scan": "component_method.source_scan.prepare_inputs",
    "extract": "component_method.component_build.run_extraction",
    "curate": "component_method.component_build.curate_components",
    "prepare_reviews": "component_method.component_build.prepare_reviews",
    "review": "component_method.component_build.run_reviews",
    "finalize_review": "component_method.component_build.finalize_single_review",
    "retrieval": "component_method.retrieval.run_retrieval",
    "task": "component_method.task_execution.run_task",
    "report": "component_method.reporting.summarize",
}

# Steps that accept worker/resume options from the block CLI.
WORKER_STEPS = frozenset({"extract", "review"})
RESUME_STEPS = frozenset({"extract", "review"})


def _publish_module(mode: str) -> str:
    if mode == "migration_direct":
        return "component_method.library_publish.publish_migration"
    if mode == "unreviewed":
        return "component_method.library_publish.publish_unreviewed"
    return "component_method.library_publish.publish_library"


def _step_argv(step: str, args: argparse.Namespace, config: dict) -> list[str]:
    argv: list[str] = []
    if step in RESUME_STEPS and args.resume:
        argv.append("--resume")
    if step in WORKER_STEPS and args.workers is not None:
        argv.extend(("--workers", str(args.workers)))
    if step == "publish_library":
        mode = args.publish_mode or publish_mode(config)
        argv.extend(("--mode", mode))
    return argv


def _run_module(module: str, argv: list[str]) -> None:
    sys.argv = [module, *argv]
    runpy.run_module(module, run_name="__main__")


def _step_plan(block_name: str, args: argparse.Namespace, config: dict) -> tuple[str, ...]:
    block = resolve_block(block_name)
    if args.steps:
        requested = [item.strip() for item in args.steps.split(",") if item.strip()]
        unknown = sorted(set(requested) - set(block.steps))
        if unknown:
            raise SystemExit(f"steps outside block {block.name}: {', '.join(unknown)}")
        plan = tuple(requested)
    else:
        plan = block.steps
    return tuple(step for step in plan if step_enabled(step, config))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path)
    parser.add_argument(
        "--stage",
        required=False,
        help=(
            "block name (prepare|build|audit|publish|retrieval|task|report), "
            "the compatibility group deliver=retrieval,task, or a retired sub-stage alias"
        ),
    )
    parser.add_argument("--blocks", help="comma-separated block selection; overrides --stage")
    parser.add_argument("--steps", help="comma-separated steps inside the selected block (debug only)")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--publish-mode",
        choices=("reviewed", "unreviewed", "migration_direct"),
        help="override the workspace publish mode",
    )
    parser.add_argument("--check", action="store_true", help="print block readiness and exit")
    parser.add_argument("--list", action="store_true", help="print the block registry and exit")
    args, stage_args = parser.parse_known_args()
    if stage_args:
        parser.error(f"unrecognized arguments: {' '.join(stage_args)}")
    if args.list:
        print(json.dumps(
            [
                {
                    "name": block.name,
                    "title": block.title,
                    "steps": list(block.steps),
                    "requires": list(block.requires),
                    "produces": block.produces,
                    "scope": block.scope,
                }
                for block in BLOCKS
            ],
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.task_root is None:
        parser.error("--task-root is required")
    task_root = args.task_root.resolve()
    experiment_common.ROOT = task_root
    experiment_common.PROJECT = batch_common.PROJECT
    config = experiment_common.load_json(task_root / "config.json")

    selection = list(selected_from_config(config, args.blocks))
    if args.stage:
        selection = list(resolve_blocks(args.stage))
    if not selection:
        parser.error("--stage or --blocks is required")
    if args.steps and len(selection) != 1:
        parser.error("--steps requires exactly one selected block")

    if args.check:
        statuses = [block_status(name, task_root, config) for name in selection]
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
        return 0 if all(status["ready"] for status in statuses) else 2

    for name in selection:
        status = block_status(name, task_root, config)
        if not status["ready"]:
            print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
        block = resolve_block(name)
        for step in _step_plan(block.name, args, config):
            artifact = step_artifact(step, task_root, config)
            if args.resume and artifact is not None and artifact.is_file():
                print(f"[block:{block.name}] skip {step}: {artifact}", flush=True)
                continue
            module = (
                _publish_module(args.publish_mode or publish_mode(config))
                if step == "publish_library"
                else STEP_MODULES[step]
            )
            _run_module(module, _step_argv(step, args, config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())