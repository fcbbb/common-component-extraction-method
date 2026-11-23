#!/usr/bin/env python3
"""Fast target-API check against existing agent workspaces (no model, no build).

This is the cheap preflight for the target-API gate:

    python3 tools/check_target_api.py \
        --label new_ipp_baseline_full \
        --label new_kylin_baseline_full

It scans the task's target source dirs and any available artifact under the
existing workspace.  It does not rebuild, run hidden tests, or call a model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness import api_removal, taskmodel  # noqa: E402

DEFAULT_PARENTS = {
    "ipp": ROOT / "v1" / "ipp_vsipl_tasks",
    "kylin": ROOT / "v3" / "windows_to_kylin" / "tasks",
}


def _parent_for(label: str) -> Path:
    return DEFAULT_PARENTS["ipp"] if "ipp" in label else DEFAULT_PARENTS["kylin"]


def _artifact_candidates(workspace: Path, task: Dict[str, Any], gate: Dict[str, Any]) -> List[Path]:
    """Find artifacts that actually exist in the agent workspace."""
    result: List[Path] = []
    raw = gate.get("artifacts")
    if isinstance(raw, str):
        raw = [raw]
    for item in raw or []:
        path = Path(str(item))
        result.append(path if path.is_absolute() else workspace / path)
    build = workspace / "build"
    art = (task.get("build") or {}).get("artifact") if isinstance(task.get("build"), dict) else None
    if art:
        name = Path(str(art)).name
        result += [build / name, workspace / name]
    # Keep this bounded: large Kylin trees often have no build artifact in the
    # agent view, and a full rglob would make the "fast" check slow.
    for suffix in (".a", ".so"):
        result.extend(workspace.glob(f"build/*{suffix}"))
        result.extend(workspace.glob(f"lib/*{suffix}"))
    seen = set()
    out = []
    for p in result:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in seen and p.is_file():
            seen.add(key)
            out.append(p)
    return out


def check_one(label: str, task_root: Path, workspace: Path) -> Dict[str, Any]:
    task = taskmodel.load_task(task_root)
    gate = taskmodel.target_api_gate(task)
    task_id = taskmodel.task_id(task)
    row: Dict[str, Any] = {
        "label": label,
        "task": task_id,
        "workspace": str(workspace),
        "status": "skip",
        "gate": gate,
        "source_hits": 0,
        "artifact_hits": 0,
        "errors": [],
    }
    if not gate:
        row["status"] = "skip"
        row["reason"] = "no target_api gate"
        return row
    if not workspace.is_dir():
        row["status"] = "skip"
        row["reason"] = "missing workspace"
        return row
    source_dirs = [
        str((workspace / str(p)).resolve()) if not Path(str(p)).is_absolute() else str(p)
        for p in (gate.get("source_dirs") or ["src"])
    ]
    artifacts = _artifact_candidates(workspace, task, gate)
    result = api_removal.scan(
        artifacts=[str(p) for p in artifacts],
        symbol_regex=gate.get("symbol_regex"),
        source_dirs=source_dirs,
        source_regex=gate.get("source_regex"),
        exclude_dirs=gate.get("exclude_dirs"),
        exclude_globs=gate.get("exclude_globs"),
        positive=True,
    )
    row["status"] = result["status"]
    row["source_hits"] = len(result.get("source_hits") or [])
    row["artifact_hits"] = len(result.get("symbols") or [])
    row["artifact_paths"] = [str(p) for p in artifacts]
    row["errors"] = result.get("errors") or []
    row["detail"] = result
    return row


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", action="append", required=True)
    ap.add_argument("--workspace-root", default=str(ROOT / "reports/bench/workspaces"))
    ap.add_argument("--json", default="")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    rows: List[Dict[str, Any]] = []
    for label in args.label:
        parent = _parent_for(label)
        root = Path(args.workspace_root) / label
        if not root.is_dir():
            rows.append({"label": label, "status": "skip", "reason": "missing label workspace root"})
            continue
        for workspace in sorted(root.iterdir()):
            if not workspace.is_dir() or not workspace.name.endswith("-r1"):
                continue
            task_id = workspace.name[:-3]
            task_root = parent / task_id
            if not task_root.is_dir():
                rows.append({"label": label, "task": task_id, "workspace": str(workspace), "status": "skip", "reason": "missing task package"})
                continue
            row = check_one(label, task_root, workspace)
            rows.append(row)
            if not args.quiet:
                print(f"{label:28} {task_id:32} {row['status']:4} source={row.get('source_hits',0)} artifact={row.get('artifact_hits',0)} {row.get('reason','')}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if all(r.get("status") in {"pass", "skip"} for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
