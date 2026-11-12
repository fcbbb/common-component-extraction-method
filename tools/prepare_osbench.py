#!/usr/bin/env python3
"""Prepare the OS-Bench windows2linux C++ tasks for the component pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
RELEASE = REPOSITORY.parent
DEFAULT_DATASET = RELEASE / "datasets" / "osbench" / "dataset" / "windows2linux_cpp.jsonl"
DEFAULT_WORKSPACE = REPOSITORY / "work" / "osbench"

sys.path[:0] = [str(REPOSITORY), str(REPOSITORY / "src")]

from dataset_adapters.osbench import (  # noqa: E402
    prepare_osbench,
    preflight_workspace,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=REPOSITORY,
        help="Component-method project root; the workspace gets a repository symlink to it.",
    )
    parser.add_argument(
        "--image-prefix",
        default="component-method/osbench-cpp",
        help=(
            "Prepared runtime image prefix. The task ID is appended as the tag; "
            "the dataset's official image is used when the prepared image is absent."
        ),
    )
    parser.add_argument(
        "--task",
        action="append",
        help="Only prepare the selected task ID; repeatable.",
    )
    parser.add_argument(
        "--expect-count",
        type=int,
        default=6,
        help="Expected number of tasks when --task is not supplied (default: 6).",
    )
    parser.add_argument(
        "--no-materialize-sources",
        action="store_true",
        help="Reuse an existing source snapshot instead of copying it from Docker.",
    )
    parser.add_argument(
        "--compile-commands",
        choices=("auto", "off", "configure"),
        default="auto",
        help=(
            "auto: use the image build, then try a cmake configure; "
            "off: do not generate; configure: require a cmake configure attempt."
        ),
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_API_BASE", ""),
        help="Model API base written to the workspace config; defaults to OPENAI_API_BASE.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Replace existing prepared sources/packages for the selected tasks.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the OS-Bench preflight immediately after preparation.",
    )
    parser.add_argument(
        "--require-model-env",
        action="store_true",
        help="With --check, require OPENAI_API_KEY and OPENAI_API_BASE.",
    )
    parser.add_argument(
        "--run-scan",
        action="store_true",
        help="With --check, run a C++ source scan to count files and units.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=20,
        help="With --run-scan, parse at most this many files; 0 means all.",
    )
    args = parser.parse_args()

    expected_count = args.expect_count if not args.task else None
    if not args.api_base:
        print(
            "warning: OPENAI_API_BASE is empty; set it before running model stages.",
            file=sys.stderr,
        )
    summary = prepare_osbench(
        args.dataset,
        args.workspace,
        args.project_root,
        image_prefix=args.image_prefix or None,
        task_ids=args.task,
        expected_count=expected_count,
        extract_sources=not args.no_materialize_sources,
        compile_commands_mode=args.compile_commands,
        api_base=args.api_base,
        refresh=args.refresh,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.check:
        result = preflight_workspace(
            args.workspace,
            task_ids=args.task,
            require_model_env=args.require_model_env,
            run_scan=args.run_scan,
            scan_limit=args.scan_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    print(
        "\nNext commands:\n"
        f"  export COMPONENT_METHOD_RELEASE_ROOT={args.workspace}\n"
        f"  export COMPONENT_METHOD_RUN_ROOT={args.workspace}\n"
        f"  python tools/preflight.py --workspace {args.workspace} --require-model-env\n"
        f"  python -m component_method.workflow.run_batch --stage candidates --task-order manifest\n",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())