#!/usr/bin/env python3
"""Validate one or more migration task-package trees.

Usage::

    python3 tools/verify_task.py --parent windows_to_kylin/tasks
    python3 tools/verify_task.py --parent windows_to_kylin/tasks \
        --parent cuda_to_musa/tasks --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness.verify import verify_parent, verify_task  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parent", action="append", default=[])
    ap.add_argument("--task-root", action="append", default=[])
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not args.parent and not args.task_root:
        ap.error("give at least one --parent or --task-root")

    results: List[Dict[str, Any]] = []
    for parent in args.parent:
        results.extend(verify_parent(Path(parent), strict=args.strict))
    for task in args.task_root:
        results.append(verify_task(Path(task), strict=args.strict))

    ok = all(item["ok"] for item in results)
    if args.json:
        print(json.dumps({"ok": ok, "tasks": results}, indent=2, ensure_ascii=False))
    else:
        for item in results:
            mark = "OK  " if item["ok"] else "FAIL"
            print(
                f"{mark} {item['task']:<34} scenario={item.get('scenario')!s:<16} "
                f"level={item.get('level')!s:<4} errors={len(item['errors'])} "
                f"warnings={len(item['warnings'])}"
            )
            for err in item["errors"]:
                print(f"     ERROR {err}")
            for warn in item["warnings"]:
                print(f"     WARN  {warn}")
        print(f"VERIFY={'PASS' if ok else 'FAIL'} tasks={len(results)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())