#!/usr/bin/env python3
"""Unified evaluator entry point for migration task packages.

The runner is intentionally command-driven: ``task.yaml`` owns the build and
hidden-test commands, and this module only supplies paths, timeouts, JSON
reporting and the shared API-removal gate.

Usage::

    python3 shared/harness/runner.py --task-root tasks/l1_poco_thread \
        --golden hidden --build-dir build_hidden

Exit codes: 0 = all executed gates pass, 1 = a gate fails, 2 = bad task.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import
    from . import api_removal, taskmodel
except ImportError:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from shared.harness import api_removal, taskmodel  # type: ignore


def _gate_dict(task: Dict[str, Any]) -> Dict[str, Any]:
    gates = task.get("gates") or {}
    api = gates.get("api_removal") if isinstance(gates, dict) else None
    return api if isinstance(api, dict) else {}


def _artifacts(task: Dict[str, Any], work: Path, build: Path) -> List[str]:
    api = _gate_dict(task)
    raw = api.get("artifacts")
    if raw is None:
        raw = (task.get("build") or {}).get("artifact")
    if isinstance(raw, str):
        raw = [raw]
    root = Path(task.get("_root") or work)
    golden = root / "harness" / "golden"
    out: List[str] = []
    for item in raw or []:
        if not str(item).strip():
            continue
        expanded = taskmodel.expand_command(
            str(item), root=root, work=work, build=build, golden=golden
        )
        path = Path(expanded)
        if not path.is_absolute():
            path = work / path
        if not path.exists():
            alt = build / Path(str(item)).name
            if alt.exists():
                path = alt
        out.append(str(path))
    return out


def run(
    task_root: str,
    *,
    build_dir: Optional[str] = None,
    work_dir: Optional[str] = None,
    golden: Optional[str] = None,
    skip_build: bool = False,
    skip_hidden: bool = False,
    skip_api: bool = False,
    run_public: bool = False,
    timeout: int = 3600,
) -> Dict[str, Any]:
    task = taskmodel.load_task(task_root)
    root = taskmodel.root_of(task)
    work = taskmodel.work_dir(task, work_dir)
    build = taskmodel.build_dir(task, build_dir)
    golden_path = taskmodel.golden_dir(task, golden)
    result: Dict[str, Any] = {
        "task": taskmodel.task_id(task),
        "scenario": task.get("scenario"),
        "level": task.get("level"),
        "root": str(root),
        "work": str(work),
        "build_dir": str(build),
        "golden": str(golden_path),
        "build": "skipped",
        "public_tests": "skipped",
        "tests": "skipped",
        "api_removal": "skipped",
        "log": "",
    }

    extra = {"task_root": str(root), "task_id": taskmodel.task_id(task)}
    env = {
        "TASK_ROOT": str(root),
        "WORK_DIR": str(work),
        "BUILD_DIR": str(build),
        "GOLDEN_DIR": str(golden_path),
    }

    build_cmd = taskmodel.command_of(task, "build")
    build_mode = str((task.get("build") or {}).get("mode", "command"))
    if not skip_build and build_cmd and build_mode != "none":
        cmd = taskmodel.expand_command(
            build_cmd, root=root, work=work, build=build, golden=golden_path, extra=extra
        )
        rc, out = taskmodel.run_command(cmd, cwd=work, env=env, timeout=timeout)
        result["build"] = "ok" if rc == 0 else "fail"
        result["log"] += out[-6000:]
        if rc != 0:
            result["status"] = "fail"
            return result

    if run_public:
        public_cmd = taskmodel.command_of(task, "public_tests")
        if public_cmd:
            cmd = taskmodel.expand_command(
                public_cmd, root=root, work=work, build=build, golden=golden_path, extra=extra
            )
            rc, out = taskmodel.run_command(cmd, cwd=work, env=env, timeout=timeout)
            result["public_tests"] = "pass" if rc == 0 else "fail"
            result["log"] += out[-4000:]
            if rc != 0:
                result["status"] = "fail"
                return result

    hidden_cmd = taskmodel.command_of(task, "hidden_tests")
    if not skip_hidden and hidden_cmd:
        cmd = taskmodel.expand_command(
            hidden_cmd, root=root, work=work, build=build, golden=golden_path, extra=extra
        )
        rc, out = taskmodel.run_command(cmd, cwd=work, env=env, timeout=timeout)
        result["tests"] = "pass" if rc == 0 else "fail"
        result["log"] += out[-6000:]
        result.update(taskmodel.parse_summary(out))
        if rc != 0:
            result["status"] = "fail"
            return result

    if not skip_api:
        api_cmd = taskmodel.command_of(task, "gates")
        # ``gates.api_removal`` may be a shell command string.
        api_gate = (task.get("gates") or {}).get("api_removal")
        if isinstance(api_gate, str):
            cmd = taskmodel.expand_command(
                api_gate, root=root, work=work, build=build, golden=golden_path, extra=extra
            )
            rc, out = taskmodel.run_command(cmd, cwd=work, env=env, timeout=timeout)
            result["api_removal"] = "pass" if rc == 0 else "fail"
            result["log"] += out[-4000:]
            if rc != 0:
                result["status"] = "fail"
                return result
        elif isinstance(api_gate, dict):
            api_result = api_removal.scan(
                artifacts=_artifacts(task, work, build),
                symbol_regex=api_gate.get("symbol_regex"),
                source_dirs=[
                    str((work / p).resolve()) if not Path(p).is_absolute() else p
                    for p in (api_gate.get("source_dirs") or ["."])
                ],
                source_regex=api_gate.get("source_regex"),
                exclude_dirs=api_gate.get("exclude_dirs"),
                exclude_globs=api_gate.get("exclude_globs"),
                expect_fail=api_gate.get("expect_fail", False),
            )
            result["api_removal"] = api_result["status"]
            result["api_detail"] = api_result
            if api_result["status"] == "fail":
                result["status"] = "fail"
                return result
            if api_result["status"] == "error":
                result["status"] = "error"
                return result

    result["status"] = "pass"
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", required=True)
    ap.add_argument("--build-dir", default=None)
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--golden", default=None, help="hidden golden/case directory")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-hidden", action="store_true")
    ap.add_argument("--skip-api", action="store_true")
    ap.add_argument("--public", action="store_true", help="also run public tests")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args(argv)

    try:
        result = run(
            args.task_root,
            build_dir=args.build_dir,
            work_dir=args.work_dir,
            golden=args.golden,
            skip_build=args.skip_build,
            skip_hidden=args.skip_hidden,
            skip_api=args.skip_api,
            run_public=args.public,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("status") == "pass":
        return 0
    if result.get("status") == "fail":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())