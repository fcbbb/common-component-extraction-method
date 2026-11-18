#!/usr/bin/env python3
"""Positive-control runner: restore a task's gold answer and run the grader.

This is the P0 "gold sanity" helper.  It answers one question per task:

    If the upstream reference implementation is submitted, does the task's
    build + hidden tests + API gate actually pass?

A failing gold answer means the task package or the target environment is
broken; it must be fixed before any agent evaluation.  The script never
edits the gold tree and never turns a skipped gate into a pass.

What it does per scenario:

* ``windows_to_kylin`` -- runs ``prepare.sh`` (unless ``--no-prepare``),
  copies ``gold/.`` over ``work/`` and runs ``shared/harness/runner.py``.
* ``cuda_to_musa`` -- tasks with an upstream MUSA gold file
  (MultiKernelBench's ``prompts/musa_new_model_*.py``) are run, with the gold
  copied to ``work/submission/<op>_submission.py``.  A task without upstream
  gold may still carry a project-authored control under ``gold_authored/``;
  that file is copied in the same way but reported as project-authored.  Tasks
  with neither are reported as ``skip: judge-only``.
* ``cuda_to_ascend`` -- the archived Ascend scenario.  Only tasks with an
  upstream Ascend C gold file (``prompts/ascendc_new_model_*.py``) are run.
  CANN Bench tasks have no upstream submission and are reported as
  ``skip: judge-only`` instead of being counted as passing.

After a run the task's ``work/`` tree contains the answer.  Re-run
``prepare.sh`` (or use a scratch copy) before evaluating an agent.

Usage::

    python3 tools/gold_sanity.py --parent windows_to_kylin/tasks --level L1
    python3 tools/gold_sanity.py --parent windows_to_kylin/tasks --exclude negative_win32_eventlog
    python3 tools/gold_sanity.py --parent cuda_to_musa/tasks --only b_l1_leaky_relu
    python3 tools/gold_sanity.py --parent archive/cuda_to_ascend/tasks --only b_l1_mk_leaky_relu
    python3 tools/gold_sanity.py --task-root windows_to_kylin/tasks/l1_poco_thread --dry-run

Exit codes: 0 = all executed gold runs passed (skips allowed),
1 = at least one gold run failed, 2 = setup/evaluation error, 3 = no tasks.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness import taskmodel  # noqa: E402

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def _load_provenance(root: Path) -> Dict[str, Any]:
    path = root / "provenance.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def _run(cmd: Sequence[str], *, cwd: Path, timeout: int) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _prepare(root: Path, timeout: int) -> Tuple[bool, str]:
    prepare = root / "prepare.sh"
    if not prepare.is_file():
        return False, "prepare.sh is missing"
    rc, out = _run(["bash", str(prepare)], cwd=root, timeout=timeout)
    return rc == 0, out


def _work_is_ready(root: Path, commit: str) -> bool:
    work = root / "work"
    if not work.is_dir():
        return False
    if not any(work.iterdir()):
        return False
    marker = work / ".source_commit"
    if marker.is_file() and commit:
        recorded = marker.read_text(encoding="utf-8", errors="replace").strip()
        return recorded == commit
    return True


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy ``src`` over ``dst`` while keeping existing files.

    ``shutil.copytree(dirs_exist_ok=True)`` needs Python 3.8; Kylin V10 ships
    Python 3.7, so merge the tree manually.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in {"__pycache__"} or item.suffix in {".pyc", ".pyo"}:
            continue
        target = dst / item.name
        if item.is_dir():
            _copy_tree(item, target)
        else:
            shutil.copy2(item, target)


def _find_gold(root: Path, rel: str) -> Optional[Path]:
    gold = root / "gold"
    exact = gold / rel
    if exact.is_file():
        return exact
    name = Path(rel).name
    matches = [p for p in gold.rglob(name) if p.is_file() and "__pycache__" not in p.parts]
    return matches[0] if matches else None


def _restore_kylin_gold(root: Path) -> Tuple[Optional[str], List[str]]:
    gold = root / "gold"
    if not gold.is_dir() or not any(p.is_file() for p in gold.rglob("*")):
        return "no gold/ tree (run prepare.sh first)", []
    work = root / "work"
    if not work.is_dir():
        return "work/ is missing (run prepare.sh first)", []
    _copy_tree(gold, work)
    restored = [
        str(p.relative_to(gold))
        for p in gold.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]
    return None, restored


def _restore_ipp_gold(
    root: Path, task: Dict[str, Any], prov: Dict[str, Any]
) -> Tuple[Optional[str], List[str]]:
    """Replace the vendored IPP source with the reference migration.

    The package keeps the IPP original in ``src/`` and the VSIPL answer in
    ``gold/``.  Submission is simulated by swapping the single ``src/`` file
    for the gold implementation while keeping the original file name, so the
    CMake ``src/*`` glob still sees exactly one translation unit.
    """
    gold_rel = str(task.get("gold_patch") or "")
    work = root / "work"
    if not work.is_dir():
        return "work/ is missing (run prepare.sh first)", []
    if not gold_rel:
        return "gold_patch is missing", []
    gold = root / gold_rel
    if not gold.is_file():
        return f"gold file not found: {gold_rel}", []

    src_dir = work / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    originals = [p for p in src_dir.iterdir() if p.is_file()]
    target_name = originals[0].name if len(originals) == 1 else gold.name
    for item in originals:
        item.unlink()
    target = src_dir / target_name
    shutil.copy2(gold, target)
    return None, [f"{gold_rel} -> {target.relative_to(root)}"]


def _restore_ascend_gold(
    root: Path, task: Dict[str, Any], prov: Dict[str, Any]
) -> Tuple[Optional[str], List[str]]:
    src = task.get("source") or {}
    gold_files = _as_list(prov.get("gold_files") or src.get("gold_files"))
    work = root / "work"
    if not work.is_dir():
        return "work/ is missing (run prepare.sh first)", []

    # CANN Bench tasks have no upstream submission.  When a hand-written
    # evaluator-only reference exists at gold/submission/, use it.
    if not gold_files:
        local = root / "gold" / "submission"
        if local.is_dir() and any(local.iterdir()):
            submission = work / "submission"
            _copy_tree(local, submission)
            return None, [f"gold/submission -> work/submission (local reference)"]
        return "judge-only: no upstream gold submission", []

    submission = work / "submission"
    submission.mkdir(parents=True, exist_ok=True)

    restored: List[str] = []
    for rel in gold_files:
        found = _find_gold(root, rel)
        if found is None:
            return f"gold file not found: {rel}", restored
        stem = found.stem
        if stem.startswith("ascendc_new_model_"):
            op = stem[len("ascendc_new_model_") :]
            target = submission / f"{op}_submission.py"
        elif stem.startswith("ascendc_direct_launch_model_"):
            op = stem[len("ascendc_direct_launch_model_") :]
            target = submission / f"{op}_submission.py"
        else:
            target = submission / found.name
        shutil.copy2(found, target)
        restored.append(f"{found.relative_to(root)} -> {target.relative_to(root)}")
    return None, restored


def _restore_musa_gold(
    root: Path, task: Dict[str, Any], prov: Dict[str, Any]
) -> Tuple[Optional[str], List[str]]:
    """Restore an upstream MultiKernelBench MUSA sample as the submission."""
    src = task.get("source") or {}
    gold_files = _as_list(prov.get("gold_files") or src.get("gold_files"))
    work = root / "work"
    if not work.is_dir():
        return "work/ is missing (run prepare.sh first)", []
    if not gold_files:
        # No upstream sample.  A project-authored control, when present, still
        # exercises the same evaluator; it is labelled so it is never confused
        # with upstream gold in the report.
        authored = root / "gold_authored"
        files = sorted(p for p in authored.glob("*.py") if p.is_file()) if authored.is_dir() else []
        if not files:
            return "judge-only: no upstream MUSA submission", []
        submission = work / "submission"
        submission.mkdir(parents=True, exist_ok=True)
        restored: List[str] = []
        for found in files:
            target = submission / found.name
            shutil.copy2(found, target)
            restored.append(
                f"{found.relative_to(root)} -> {target.relative_to(root)} (project-authored)"
            )
        return None, restored

    submission = work / "submission"
    submission.mkdir(parents=True, exist_ok=True)

    restored: List[str] = []
    for rel in gold_files:
        found = _find_gold(root, rel)
        if found is None:
            return f"gold file not found: {rel}", restored
        stem = found.stem
        if stem.startswith("musa_new_model_"):
            op = stem[len("musa_new_model_") :]
            target = submission / f"{op}_submission.py"
        else:
            target = submission / found.name
        shutil.copy2(found, target)
        restored.append(f"{found.relative_to(root)} -> {target.relative_to(root)}")
    return None, restored


def _run_runner(root: Path, build_dir: Path, timeout: int) -> Tuple[int, str, Optional[Dict[str, Any]]]:
    cmd = [
        sys.executable,
        str(ROOT / "shared" / "harness" / "runner.py"),
        "--task-root",
        str(root),
        "--build-dir",
        str(build_dir),
    ]
    rc, out = _run(cmd, cwd=ROOT, timeout=timeout)
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    return rc, out, parsed


def _iter_roots(args: argparse.Namespace) -> List[Path]:
    roots: List[Path] = []
    for item in args.task_root:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        if (path / "task.yaml").is_file():
            roots.append(path)
    for parent in args.parent:
        path = Path(parent)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_dir():
            continue
        for child in sorted(path.iterdir()):
            if child.is_dir() and (child / "task.yaml").is_file():
                roots.append(child)
    if args.only:
        wanted = set(args.only)
        roots = [root for root in roots if root.name in wanted]
    if args.exclude:
        excluded = set(args.exclude)
        roots = [root for root in roots if root.name not in excluded]
    if args.level:
        levels = {level.upper() for level in args.level}
        kept = []
        for root in roots:
            try:
                task = taskmodel.load_task(root)
            except Exception:  # noqa: BLE001 - report the parse error later
                continue
            if str(task.get("level", "")).upper() in levels:
                kept.append(root)
        roots = kept
    # Preserve order but drop duplicates.
    seen = set()
    unique = []
    for root in roots:
        key = root.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _summarize(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return counts


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", action="append", default=[], help="one task package")
    ap.add_argument("--parent", action="append", default=[], help="task package parent")
    ap.add_argument("--only", action="append", default=[], help="only these task ids")
    ap.add_argument("--exclude", action="append", default=[], help="skip these task ids")
    ap.add_argument("--level", action="append", default=[], help="only L1/L2/L3")
    ap.add_argument("--build-root", default="/tmp/migration-gold-build")
    ap.add_argument("--report-dir", default="reports/gold_sanity")
    ap.add_argument("--label", default="gold")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--prepare-timeout", type=int, default=1800)
    ap.add_argument("--no-prepare", action="store_true", help="use the existing work/ tree")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.task_root and not args.parent:
        ap.error("give --task-root or --parent")

    roots = _iter_roots(args)
    if not roots:
        print("no task packages found", file=sys.stderr)
        return 3

    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = ROOT / report_dir
    build_root = Path(args.build_root)
    if not args.dry_run:
        report_dir.mkdir(parents=True, exist_ok=True)
        build_root.mkdir(parents=True, exist_ok=True)

    started_wall = datetime.now(timezone.utc).isoformat()
    results: List[Dict[str, Any]] = []

    def _write_record(record: Dict[str, Any]) -> None:
        """Persist one task's result immediately.

        Reports used to be written only after every task finished, so a killed
        container (WSL shutdown, Docker restart) lost all completed work.  Write
        each record as soon as it is final.
        """
        if args.dry_run:
            return
        try:
            (report_dir / f"{record['task']}.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            print(f"WARN cannot write report for {record['task']}: {exc}")

    for root in roots:
        try:
            task = taskmodel.load_task(root)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "task": root.name,
                    "status": "error",
                    "detail": f"cannot parse task.yaml: {exc}",
                }
            )
            print(f"ERROR {root.name}: cannot parse task.yaml: {exc}")
            _write_record(results[-1])
            continue

        task_id = str(task.get("task_id") or root.name)
        scenario = str(task.get("scenario") or "")
        prov = _load_provenance(root)
        src = task.get("source") or {}
        commit = str(prov.get("commit") or src.get("commit") or "")
        level = task.get("level")
        started = time.time()
        record: Dict[str, Any] = {
            "task": task_id,
            "scenario": scenario,
            "level": level,
            "commit": commit,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "gold_restored": [],
            "prepare": "skipped",
            "detail": "",
            "duration_s": 0.0,
        }

        if args.dry_run:
            record["status"] = "skip"
            record["detail"] = "dry-run"
            results.append(record)
            print(f"DRY  {task_id:<32} {scenario:<16} {level}")
            continue

        # 1. Materialize the upstream snapshot if needed.
        needs_prepare = not _work_is_ready(root, commit)
        if needs_prepare and not args.no_prepare:
            ok, out = _prepare(root, args.prepare_timeout)
            record["prepare"] = "ok" if ok else "fail"
            record["prepare_log"] = out[-4000:]
            if not ok:
                record["status"] = "error"
                record["detail"] = "prepare.sh failed"
                record["duration_s"] = round(time.time() - started, 1)
                results.append(record)
                print(f"ERROR {task_id:<31} prepare.sh failed")
                _write_record(record)
                continue
        elif needs_prepare:
            record["status"] = "error"
            record["detail"] = "work/ is not materialized and --no-prepare was given"
            record["duration_s"] = round(time.time() - started, 1)
            results.append(record)
            print(f"ERROR {task_id:<31} work/ not materialized (--no-prepare)")
            _write_record(record)
            continue

        # 2. Restore the gold answer.
        if scenario == "windows_to_kylin":
            error, restored = _restore_kylin_gold(root)
        elif scenario == "ipp_to_vsipl":
            error, restored = _restore_ipp_gold(root, task, prov)
        elif scenario == "cuda_to_musa":
            error, restored = _restore_musa_gold(root, task, prov)
        elif scenario == "cuda_to_ascend":
            error, restored = _restore_ascend_gold(root, task, prov)
        else:
            error, restored = f"unsupported scenario: {scenario}", []
        record["gold_restored"] = restored
        if error:
            if error.startswith("judge-only"):
                record["status"] = "skip"
                record["detail"] = error
                record["duration_s"] = round(time.time() - started, 1)
                results.append(record)
                print(f"SKIP {task_id:<31} {error}")
                _write_record(record)
                continue
            record["status"] = "error"
            record["detail"] = error
            record["duration_s"] = round(time.time() - started, 1)
            results.append(record)
            print(f"ERROR {task_id:<31} {error}")
            _write_record(record)
            continue

        # 3. Build + hidden tests + API gate.
        build_dir = build_root / task_id
        if build_dir.exists():
            shutil.rmtree(build_dir)
        rc, out, parsed = _run_runner(root, build_dir, args.timeout)
        record["runner_rc"] = rc
        record["runner"] = parsed
        record["log_tail"] = out[-8000:]
        if rc == 0 and (parsed or {}).get("status") == "pass":
            record["status"] = "pass"
        else:
            record["status"] = "fail"
            if parsed and parsed.get("status"):
                record["detail"] = f"runner status={parsed.get('status')}"
            else:
                record["detail"] = f"runner exited {rc}"
        record["duration_s"] = round(time.time() - started, 1)
        results.append(record)
        _write_record(record)
        print(
            f"{record['status'].upper():<4} {task_id:<31} {scenario:<16} "
            f"{record['duration_s']:7.1f}s {record['detail']}"
        )

    summary = {
        "label": args.label,
        "started_at": started_wall,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "image": os.environ.get("MIGRATION_BENCH_IMAGE", ""),
        "counts": _summarize(results),
        "results": results,
    }

    if not args.dry_run:
        for result in results:
            _write_record(result)
        (report_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"report: {report_dir / 'summary.json'}")

    counts = summary["counts"]
    print(
        "SUMMARY "
        + " ".join(f"{key}={value}" for key, value in counts.items())
        + f" label={args.label}"
    )

    if counts["error"]:
        return 2
    if counts["fail"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())