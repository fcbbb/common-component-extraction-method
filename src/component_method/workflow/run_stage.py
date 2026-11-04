#!/usr/bin/env python3
"""在指定任务根目录中运行最终流水线的一个阶段。"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from component_method.workflow import batch_common, experiment_common


STAGES = {
    "prepare": "component_method.source_scan.prepare_inputs",
    "extract": "component_method.component_build.run_extraction",
    "curate": "component_method.component_build.curate_components",
    "prepare_reviews": "component_method.component_build.prepare_reviews",
    "review": "component_method.component_build.run_reviews",
    "finalize_review": "component_method.component_build.finalize_single_review",
    "publish": "component_method.library_publish.publish_library",
    "retrieval": "component_method.retrieval.run_retrieval",
    "task": "component_method.task_execution.run_task",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--stage", choices=tuple(STAGES), required=True)
    args, stage_args = parser.parse_known_args()
    task_root = args.task_root.resolve()
    experiment_common.ROOT = task_root
    experiment_common.PROJECT = batch_common.PROJECT
    sys.argv = [STAGES[args.stage], *stage_args]
    runpy.run_module(STAGES[args.stage], run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
