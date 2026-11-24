#!/usr/bin/env python3
"""One-click, idempotent, resumable component-first pipeline for one scenario.

Steps (each skippable and safe to re-run):

1. **corpus**  verify the frozen migration corpus; rebuild only when missing or
   when ``--verify`` fails (``build_history_corpus.py``).
2. **extract** run scan -> publish when the library is absent; with a published
   ``library_lock.json`` this step is skipped so a re-run costs nothing.  The
   extraction stages themselves are resumable (``--resume``).
3. **freeze**  read back ``library_lock.json`` + ``manifest.json`` and print the
   component count and history digest.
4. **matrix**  regenerate the component x task capability matrix (always cheap
   and deterministic) from the frozen manifest.
5. **validate** clean evaluator answers out of agent trees, then run
   ``verify_task.py`` and ``check_pins.py --offline`` over every task package.
6. **gold** (opt-in) run ``gold_sanity.py`` for the selected tasks.

Usage::

    python3 tools/component_first_pipeline.py --stage all \
        --library-dir v3/windows_to_kylin/library_generated/full_20261123/library

    # Re-validate an existing library without touching extraction:
    python3 tools/component_first_pipeline.py --stage validate

    # Positive controls for the three component-first cases:
    python3 tools/component_first_pipeline.py --stage gold \
        --only v2_poco_process --only v2_nginx_process --only v2_nginx_thread
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
PY = sys.executable or "python3"
STAGES = ["corpus", "extract", "freeze", "matrix", "validate", "gold"]
DEFAULT_SPEC = "v3/windows_to_kylin/history/spec.yaml"
DEFAULT_LIBRARY = "v3/windows_to_kylin/library_generated/full_20261123/library"
DEFAULT_TASKS = "v3/windows_to_kylin/tasks"
DEFAULT_MATRIX = "v3/windows_to_kylin/capability_matrix"
DEFAULT_SLATE = "v3/windows_to_kylin/slate.yaml"


def rel(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def say(message: str) -> None:
    print(f"[pipeline] {message}", flush=True)


def run(cmd: List[str], *, env: Optional[dict] = None, check: bool = False) -> subprocess.CompletedProcess:
    say("$ " + " ".join(cmd))
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True)
    say(f"  rc={proc.returncode} elapsed={time.time() - started:.1f}s")
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def json_run(cmd: List[str]) -> tuple[int, dict]:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"expected JSON from: {' '.join(cmd)}")
    return proc.returncode, payload


def load_dotenv() -> dict:
    """Credentials: repository/.env wins, the shell only fills gaps."""
    env = dict(os.environ)
    dotenv = PROJECT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


# --------------------------------------------------------------------------
# stages


def stage_corpus(spec: Path, rebuild: bool) -> None:
    history = spec.parent
    index = history / "index.json"
    lock = history / "lock.json"
    if not rebuild and index.is_file() and lock.is_file():
        proc = run([PY, "tools/build_history_corpus.py", "--spec", str(spec), "--verify"])
        if proc.returncode == 0:
            say("corpus verified")
            return
        say("corpus verify failed; rebuilding")
    run([PY, "tools/build_history_corpus.py", "--spec", str(spec), "--force"], check=True)


def stage_extract(spec: Path, library: Path, refresh: bool) -> None:
    if not refresh and (library / "library_lock.json").is_file() and (library / "manifest.json").is_file():
        say(f"published library already present at {library}; skipping extraction (--refresh-extract to redo)")
        return
    env = load_dotenv()
    missing = [k for k in ("OPENAI_API_BASE", "OPENAI_API_KEY", "MODEL_NAME") if not env.get(k)]
    if missing:
        raise SystemExit(f"missing model credentials: {', '.join(missing)} (repository/.env or environment)")
    run(
        [
            PY,
            "tools/extract_transformation.py",
            "--spec",
            str(spec),
            "--library",
            str(library),
            "--stage",
            "all",
            "--resume",
        ],
        env=env,
        check=True,
    )
    run(
        [
            PY,
            "tools/extract_transformation.py",
            "--spec",
            str(spec),
            "--library",
            str(library),
            "--stage",
            "verify",
        ],
        env=env,
        check=True,
    )


def stage_freeze(library: Path) -> dict:
    lock_path = library / "library_lock.json"
    manifest_path = library / "manifest.json"
    if not lock_path.is_file() or not manifest_path.is_file():
        raise SystemExit(f"no frozen library at {library} (run --stage extract first)")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    components = manifest.get("components", [])
    lock_components = lock.get("components", [])
    if len(components) != len(lock_components):
        raise SystemExit(
            f"manifest/lock component count mismatch: {len(components)} vs {len(lock_components)}"
        )
    say(
        "frozen library: "
        f"{len(components)} components, history_digest={lock.get('history_digest')}, "
        f"lock={lock_path}"
    )
    for comp in components:
        say(f"  - {comp.get('bundle_id')}  [{comp.get('capability')}]")
    return manifest


def stage_matrix(manifest_path: Path, tasks_root: Path, matrix_dir: Path, slate: Optional[Path]) -> None:
    cmd = [
        PY,
        "tools/component_task_matrix.py",
        "--library-manifest",
        str(manifest_path),
        "--tasks-root",
        str(tasks_root),
        "--output-dir",
        str(matrix_dir),
    ]
    if slate is not None and slate.is_file():
        cmd.extend(["--slate", str(slate)])
    run(cmd, check=True)
    say(f"matrix written to {matrix_dir}/matrix.md and matrix.json")


def stage_validate(tasks_root: Path, clean: bool) -> None:
    if clean:
        run([PY, "tools/clean_gold_from_work.py", "--parent", str(tasks_root)], check=True)

    rc, verify = json_run([PY, "tools/verify_task.py", "--parent", str(tasks_root), "--json"])
    tasks = verify.get("tasks", [])
    broken = [t for t in tasks if not t.get("ok")]
    warnings = sum(len(t.get("warnings") or []) for t in tasks)
    say(f"verify_task: {len(tasks) - len(broken)}/{len(tasks)} ok, {warnings} warnings")
    for task in broken:
        say(f"  BROKEN {task.get('task')}: {task.get('errors')}")
    if rc != 0 or broken:
        raise SystemExit("verify_task failed")

    rc, pins = json_run([PY, "tools/check_pins.py", "--offline", "--parent", str(tasks_root), "--json"])
    summary = pins.get("summary", {})
    say(f"check_pins (offline): {summary}")
    if summary.get("fail"):
        raise SystemExit("check_pins reported failures")


def stage_gold(tasks_root: Path, only: List[str], timeout: int, label: str) -> None:
    targets = only or ["v2_poco_process", "v2_nginx_process", "v2_nginx_thread"]
    for task in targets:
        task_root = tasks_root / task
        if not (task_root / "task.yaml").is_file():
            raise SystemExit(f"unknown task package: {task_root}")
        run(
            [
                PY,
                "tools/gold_sanity.py",
                "--task-root",
                str(task_root),
                "--label",
                f"{label}_{task}",
                "--timeout",
                str(timeout),
            ]
        )
    run([PY, "tools/clean_gold_from_work.py", "--parent", str(tasks_root)], check=True)


# --------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", action="append", choices=STAGES + ["all"], default=[])
    ap.add_argument("--spec", default=DEFAULT_SPEC)
    ap.add_argument("--library-dir", default=DEFAULT_LIBRARY)
    ap.add_argument("--tasks-root", default=DEFAULT_TASKS)
    ap.add_argument("--matrix-dir", default=DEFAULT_MATRIX)
    ap.add_argument("--slate", default=DEFAULT_SLATE)
    ap.add_argument("--rebuild-corpus", action="store_true", help="force corpus rebuild")
    ap.add_argument("--refresh-extract", action="store_true", help="re-run extraction even with a published library")
    ap.add_argument("--no-clean", action="store_true", help="keep evaluator answers that gold runs restored into work/")
    ap.add_argument("--only", action="append", default=[], help="task ids for --stage gold")
    ap.add_argument("--gold-timeout", type=int, default=3600)
    ap.add_argument("--gold-label", default="component_first")
    args = ap.parse_args(argv)

    stages = STAGES if "all" in args.stage or not args.stage else [s for s in STAGES if s in args.stage]
    spec = rel(args.spec)
    library = rel(args.library_dir)
    tasks_root = rel(args.tasks_root)
    matrix_dir = rel(args.matrix_dir)
    slate = rel(args.slate)

    say(f"stages: {', '.join(stages)}")
    if "corpus" in stages:
        stage_corpus(spec, args.rebuild_corpus)
    if "extract" in stages:
        stage_extract(spec, library, args.refresh_extract)
    manifest_path = library / "manifest.json"
    if "freeze" in stages:
        stage_freeze(library)
    if "matrix" in stages:
        stage_matrix(manifest_path, tasks_root, matrix_dir, slate)
    if "validate" in stages:
        stage_validate(tasks_root, not args.no_clean)
    if "gold" in stages:
        stage_gold(tasks_root, args.only, args.gold_timeout, args.gold_label)
    say("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())