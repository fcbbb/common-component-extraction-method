#!/usr/bin/env python3
"""Unified evaluator entry point for migration task packages.

The runner is command-driven: ``task.yaml`` owns the build and hidden-test
commands.  The agent workspace may intentionally omit upstream tests/evaluator
files; the judge overlays its source onto the full pristine work tree before
running the hidden tests.  This keeps judge tests out of the agent view while
still allowing the agent to compile and write its own tests.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import
    from . import agent_view, api_removal, taskmodel
except ImportError:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from shared.harness import agent_view, api_removal, taskmodel  # type: ignore


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


def _make_judge_work(
    *,
    task: Dict[str, Any],
    base_work: Path,
    agent_work: Path,
    temp_root: Path,
) -> Path:
    """Copy the full pristine tree and overlay only agent-visible files."""
    judge_work = temp_root / "work"
    shutil.copytree(base_work, judge_work, symlinks=True)
    # A stale base work/ must never hand the judge the answer: the removed
    # implementation has to come from the agent's overlay.
    agent_view.strip_removed_paths(judge_work, task)
    agent_view.copy_overlay(agent_work, judge_work, task, delete_missing=True)
    return judge_work


def run(
    task_root: str,
    *,
    build_dir: Optional[str] = None,
    work_dir: Optional[str] = None,
    base_work_dir: Optional[str] = None,
    golden: Optional[str] = None,
    skip_build: bool = False,
    skip_hidden: bool = False,
    skip_regression: bool = False,
    skip_api: bool = False,
    run_public: bool = False,
    timeout: int = 3600,
) -> Dict[str, Any]:
    task = taskmodel.load_task(task_root)
    root = taskmodel.root_of(task)
    source_work = taskmodel.work_dir(task, work_dir)
    base_work = taskmodel.work_dir(task, base_work_dir)
    build = taskmodel.build_dir(task, build_dir)
    golden_path = taskmodel.golden_dir(task, golden)
    result: Dict[str, Any] = {
        "task": taskmodel.task_id(task),
        "scenario": task.get("scenario"),
        "level": task.get("level"),
        "root": str(root),
        "work": str(source_work),
        "source_work": str(source_work),
        "base_work": str(base_work),
        "agent_view": "full",
        "build_dir": str(build),
        "golden": str(golden_path),
        "build": "skipped",
        "public_tests": "skipped",
        "tests": "skipped",
        "regression": "skipped",
        "api_removal": "skipped",
        "target_api": "skipped",
        "log": "",
    }

    temp_root: Optional[Path] = None
    work = source_work
    if (
        base_work.is_dir()
        and source_work.resolve() != base_work.resolve()
    ):
        temp_root = Path(tempfile.mkdtemp(prefix=f"migration-judge-{result['task']}-"))
        work = _make_judge_work(
            task=task,
            base_work=base_work,
            agent_work=source_work,
            temp_root=temp_root,
        )
        result["work"] = str(work)
        result["agent_view"] = "filtered_overlay"

    try:
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

        regression_cmd = taskmodel.command_of(task, "regression_tests")
        if not skip_hidden and not skip_regression and regression_cmd:
            cmd = taskmodel.expand_command(
                regression_cmd, root=root, work=work, build=build, golden=golden_path, extra=extra
            )
            rc, out = taskmodel.run_command(cmd, cwd=work, env=env, timeout=timeout)
            result["regression"] = "pass" if rc == 0 else "fail"
            result["log"] += out[-4000:]
            result.update({f"regression_{k}": v for k, v in taskmodel.parse_summary(out).items()})
            if rc != 0:
                result["status"] = "fail"
                return result

        if not skip_api:
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

            target_gate = taskmodel.target_api_gate(task)
            if isinstance(target_gate, dict):
                target_dirs = target_gate.get("source_dirs") or ["src"]
                target_result = api_removal.scan(
                    artifacts=_artifacts(task, work, build),
                    symbol_regex=target_gate.get("symbol_regex"),
                    source_dirs=[
                        str((work / p).resolve()) if not Path(p).is_absolute() else p
                        for p in target_dirs
                    ],
                    source_regex=target_gate.get("source_regex"),
                    exclude_dirs=target_gate.get("exclude_dirs"),
                    exclude_globs=target_gate.get("exclude_globs"),
                    positive=True,
                )
                result["target_api"] = target_result["status"]
                result["target_detail"] = target_result
                if target_result["status"] == "fail":
                    result["status"] = "fail"
                    return result
                if target_result["status"] == "error":
                    result["status"] = "error"
                    return result

        result["status"] = "pass"
        return result
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", required=True)
    ap.add_argument("--build-dir", default=None)
    ap.add_argument("--work-dir", default=None)
    ap.add_argument("--base-work-dir", default=None,
                    help="full pristine work tree used for the hidden-test overlay")
    ap.add_argument("--golden", default=None, help="hidden golden/case directory")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-hidden", action="store_true")
    ap.add_argument("--skip-regression", action="store_true")
    ap.add_argument("--skip-api", action="store_true")
    ap.add_argument("--public", action="store_true", help="also run public tests")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args(argv)

    try:
        result = run(
            args.task_root,
            build_dir=args.build_dir,
            work_dir=args.work_dir,
            base_work_dir=args.base_work_dir,
            golden=args.golden,
            skip_build=args.skip_build,
            skip_hidden=args.skip_hidden,
            skip_regression=args.skip_regression,
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
