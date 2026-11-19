#!/usr/bin/env python3
"""Lint the migration datasets for agent-visible judge/test leakage."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness import taskmodel  # noqa: E402

PATTERNS = {
    "ipp_to_vsipl": r"vsip_|jvsip",
    "cuda_to_musa": r"load_inline|musa_sources|__global__|<<<|torch_musa",
    "windows_to_kylin": r"pthread_[A-Za-z0-9_]+|dlopen|dlsym|dlclose|OpenSSL|GTK|epoll|fork/exec",
}


def _parents() -> List[Path]:
    return [
        ROOT / "ipp_vsipl_tasks",
        ROOT / "windows_to_kylin" / "tasks",
        ROOT / "cuda_to_musa" / "tasks",
    ]


def lint_task(root: Path) -> Dict[str, Any]:
    task = taskmodel.load_task(root)
    task_id = taskmodel.task_id(task)
    scenario = str(task.get("scenario") or "")
    errors: List[str] = []
    spec = str(task.get("spec") or "")
    pattern = PATTERNS.get(scenario)
    if pattern:
        hits = sorted(set(re.findall(pattern, spec)))
        if hits:
            errors.append(f"visible spec contains target hint(s): {hits}")
    judge_words = sorted(set(re.findall(r"hidden|evaluator|eval_single_runner|nginx-tests", spec, re.I)))
    if judge_words:
        errors.append(f"visible spec names judge material: {judge_words}")
    readme = root / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace")
        if "## Hidden tests" in text:
            errors.append("README.md contains ## Hidden tests")
        if any(token in text for token in ("TASK.md", "hidden_tests")):
            errors.append("README.md mentions an agent-visible TASK/hidden test")
    work_task = root / "work" / "TASK.md"
    if work_task.exists():
        errors.append("work/TASK.md is agent-visible")
    return {"task": task_id, "scenario": scenario, "ok": not errors, "errors": errors}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    results = []
    for parent in _parents():
        if not parent.is_dir():
            continue
        for path in sorted(parent.glob("*/task.yaml")):
            results.append(lint_task(path.parent))
    ok = all(item["ok"] for item in results)
    if args.json:
        print(json.dumps({"ok": ok, "tasks": results}, indent=2, ensure_ascii=False))
    else:
        for item in results:
            print(("OK  " if item["ok"] else "FAIL") + f" {item['scenario']:<16} {item['task']}")
            for error in item["errors"]:
                print(f"     ERROR {error}")
        print(f"LINT={'PASS' if ok else 'FAIL'} tasks={len(results)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
