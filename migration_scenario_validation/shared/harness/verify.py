#!/usr/bin/env python3
"""Static validator for migration task packages.

Checks the common task schema, provenance, gold/answer separation and the
recipe files that let a package be regenerated from its upstream commit.

Usage::

    python3 shared/harness/verify.py --task-root tasks/l1_poco_thread
    python3 shared/harness/verify.py --parent windows_to_kylin/tasks --json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:  # package import
    from . import taskmodel
except ImportError:  # direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from shared.harness import taskmodel  # type: ignore

SCENARIOS = {"ipp_to_vsipl", "windows_to_kylin", "cuda_to_musa", "cuda_to_ascend"}
REQUIRED_GATES = ("build", "api_removal", "behavior")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def verify_task(root: os.PathLike | str, *, strict: bool = False) -> Dict[str, Any]:
    root = Path(root).resolve()
    errors: List[str] = []
    warnings: List[str] = []

    if not (root / "task.yaml").is_file():
        return {
            "task": root.name,
            "root": str(root),
            "ok": False,
            "errors": ["missing task.yaml"],
            "warnings": [],
        }

    try:
        task = taskmodel.load_task(root)
    except Exception as exc:  # noqa: BLE001 - report parse error
        return {
            "task": root.name,
            "root": str(root),
            "ok": False,
            "errors": [f"cannot parse task.yaml: {exc}"],
            "warnings": [],
        }

    for key in taskmodel.REQUIRED_KEYS:
        if key not in task:
            errors.append(f"missing task.yaml key: {key}")

    tid = str(task.get("task_id") or "")
    if tid and tid != root.name:
        errors.append(f"task_id '{tid}' does not match directory '{root.name}'")
    if task.get("scenario") not in SCENARIOS:
        errors.append(f"unknown scenario: {task.get('scenario')!r}")

    source = task.get("source") or {}
    for key in ("repo", "commit", "license"):
        if not source.get(key):
            errors.append(f"source.{key} is missing")
    if source.get("repo") and not str(source["repo"]).startswith(("http://", "https://", "git@")):
        warnings.append(f"source.repo is not a URL: {source['repo']!r}")

    build = task.get("build") or {}
    if not build.get("command") and build.get("mode") != "none":
        errors.append("build.command is missing (or set build.mode: none)")
    hidden = task.get("hidden_tests") or {}
    if isinstance(hidden, dict) and not hidden.get("command"):
        errors.append("hidden_tests.command is missing")

    gates = task.get("gates") or {}
    if not isinstance(gates, dict):
        errors.append("gates must be a mapping")
    else:
        for key in REQUIRED_GATES:
            if key not in gates:
                errors.append(f"gates.{key} is missing")

    negative = bool(task.get("negative"))
    if negative and task.get("expected_api_removal") != "fail":
        errors.append("negative task must set expected_api_removal: fail")

    # Provenance and answer separation.
    provenance = _load_json(root / "provenance.json")
    if provenance is None:
        errors.append("missing or invalid provenance.json")
        provenance = {}
    for key in ("repo", "commit", "license"):
        if provenance.get(key) and source.get(key) and provenance[key] != source[key]:
            errors.append(f"provenance.{key} disagrees with task.yaml")
    if provenance and not provenance.get("materialized", False):
        warnings.append("task is recipe-only (provenance.materialized=false)")

    gold_files = list(provenance.get("gold_files") or source.get("gold_files") or [])
    gold_kind = provenance.get("gold_kind") or task.get("gold_kind")
    has_gold = (
        (root / "gold").is_dir()
        or (root / "gold_patch").exists()
        or (root / "gold.patch").exists()
        or gold_kind in {"spec", "tutorial", "none"}
        or negative
    )
    if not has_gold:
        warnings.append("no gold implementation/patch found")
        if strict:
            errors.append("strict: no gold implementation/patch")

    remove = list((task.get("prepare") or {}).get("remove") or provenance.get("remove") or [])
    vendored = bool(source.get("vendored") or provenance.get("vendored"))
    if gold_files and not negative and not vendored:
        for item in gold_files:
            if item not in remove and gold_kind not in {"spec", "tutorial"}:
                warnings.append(f"gold file not in prepare.remove: {item}")

    prepare = root / "prepare.sh"
    if not prepare.is_file():
        errors.append("missing prepare.sh (recipe to materialize the snapshot)")
    else:
        if not os.access(prepare, os.X_OK):
            warnings.append("prepare.sh is not executable")

    # Visible source must not contain the gold implementation for materialized
    # packages.  This is a filename/size heuristic, not a content scan.
    visible_dirs = [d for d in (root / "source", root / "src") if d.is_dir()]
    for gold in gold_files:
        gname = Path(gold).name
        for visible in visible_dirs:
            for hit in visible.rglob(gname):
                errors.append(f"gold file visible in source tree: {hit}")
                break

    if task.get("tolerances") is None:
        warnings.append("no tolerances declared")

    return {
        "task": root.name,
        "root": str(root),
        "scenario": task.get("scenario"),
        "level": task.get("level"),
        "materialized": bool(provenance.get("materialized", False)),
        "gold_kind": gold_kind or "implementation",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def verify_parent(parent: os.PathLike | str, *, strict: bool = False) -> List[Dict[str, Any]]:
    parent = Path(parent)
    results: List[Dict[str, Any]] = []
    if not parent.is_dir():
        return results
    for child in sorted(parent.iterdir()):
        if child.is_dir() and (child / "task.yaml").is_file():
            results.append(verify_task(child, strict=strict))
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-root", help="single task package")
    group.add_argument("--parent", help="directory containing task packages")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = (
        [verify_task(args.task_root, strict=args.strict)]
        if args.task_root
        else verify_parent(args.parent, strict=args.strict)
    )
    ok = all(item["ok"] for item in results)
    if args.json:
        print(json.dumps({"ok": ok, "tasks": results}, indent=2, ensure_ascii=False))
    else:
        for item in results:
            mark = "OK  " if item["ok"] else "FAIL"
            print(f"{mark} {item['task']:<32} errors={len(item['errors'])} warnings={len(item['warnings'])}")
            for err in item["errors"]:
                print(f"     ERROR {err}")
            for warn in item["warnings"]:
                print(f"     WARN  {warn}")
        print(f"VERIFY={'PASS' if ok else 'FAIL'} tasks={len(results)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())