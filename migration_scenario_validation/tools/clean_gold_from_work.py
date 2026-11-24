#!/usr/bin/env python3
"""Remove evaluator-only answer files that a gold run copied back into work/.

``tools/gold_sanity.py`` restores ``gold/`` over a task's ``work/`` tree and
leaves it there.  A later static check then reports the answer as leaked into
the agent-visible tree.  This helper restores the prepared state: every file
present under ``gold/`` is deleted from ``work/`` at the same relative path
(and only that path).

Usage::

    python3 tools/clean_gold_from_work.py --task-root v3/windows_to_kylin/tasks/v2_poco_process
    python3 tools/clean_gold_from_work.py --parent v3/windows_to_kylin/library_generated/gold_snapshots
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]


def _gold_files(task_root: Path) -> List[Path]:
    gold = task_root / "gold"
    if not gold.is_dir():
        return []
    return [
        path
        for path in gold.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    ]


def clean_task(task_root: Path) -> List[str]:
    work = task_root / "work"
    removed: List[str] = []
    if not work.is_dir():
        return removed
    for gold_file in _gold_files(task_root):
        rel = gold_file.relative_to(task_root / "gold")
        target = work / rel
        if target.is_file() or target.is_symlink():
            target.unlink()
            removed.append(str(rel))
    return removed


def _iter_tasks(parents: Iterable[str]) -> List[Path]:
    roots: List[Path] = []
    for raw in parents:
        parent = Path(raw)
        if not parent.is_absolute():
            parent = ROOT / parent
        if (parent / "task.yaml").is_file():
            roots.append(parent)
            continue
        if parent.is_dir():
            for child in sorted(parent.iterdir()):
                if child.is_dir() and (child / "task.yaml").is_file():
                    roots.append(child)
    return roots


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", action="append", default=[])
    ap.add_argument("--parent", action="append", default=[])
    args = ap.parse_args(argv)

    roots = _iter_tasks(list(args.task_root) + list(args.parent))
    if not roots:
        ap.error("give --task-root or --parent with at least one task package")

    for task_root in roots:
        removed = clean_task(task_root)
        label = task_root.name
        if removed:
            print(f"CLEAN {label:<34} removed={len(removed)}")
            for rel in removed:
                print(f"      {rel}")
        else:
            print(f"OK    {label:<34} nothing to remove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())