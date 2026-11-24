#!/usr/bin/env python3
"""Run many benchmark arms as a bounded parallel batch.

``bench.py run`` executes one task at a time.  A component-first suite has
dozens of task x arm jobs, each taking tens of minutes, so this wrapper keeps a
fixed number of independent ``bench.py`` processes alive.

Properties:

* **bounded parallelism** — ``--workers`` jobs at once (default 3; the pytest
  workers are not serialised against each other and each holds a build tree and
  a container);
* **one job per task at a time** — two arms of the same task would fight over
  the fixed test ports in its harness even though their workspaces differ;
* **resumable** — a job whose ``attempt.json`` already exists is skipped unless
  ``--force`` is given, so an interrupted batch can be restarted;
* **inspectable** — every job writes ``batch_logs/<label>.log`` and the batch
  writes ``batch_state.json`` with pid, start/end and return code.

Usage::

    python3 tools/bench_batch.py \
        --tasks-file v3/windows_to_kylin/suite20/tasks.txt \
        --arms default,method --workers 3 --prefix s1

    # One task, both arms, dry run:
    python3 tools/bench_batch.py --task v2_file --arms default,method --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "tools" / "bench.py"
PY = sys.executable or "python3"
DEFAULT_SCENARIO = "windows_to_kylin_v3"
DEFAULT_LIBRARY = ROOT / "v3/windows_to_kylin/library_generated/full_20261123/library"
DEFAULT_BUNDLE = DEFAULT_LIBRARY
DEFAULT_METHOD_PROMPT = "config/prompts/method_retrieval_only_system.txt"
DEFAULT_STAGE_IMAGE = "migration/kylin:sp3-p2"


@dataclass
class Job:
    arm: str
    task: str
    run: int
    label: str
    log: Path
    proc: Optional[subprocess.Popen] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    rc: Optional[int] = None
    note: str = ""


class Batch:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.report_root = ROOT / "reports" / "bench"
        self.state_path = ROOT / "v3/windows_to_kylin/library_generated" / f"batch_state_{args.prefix}.json"
        self.log_dir = ROOT / "v3/windows_to_kylin/library_generated" / "batch_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.jobs: List[Job] = []
        self.tasks_root = ROOT / "v3/windows_to_kylin/tasks"

    # -- preparation ------------------------------------------------------

    def prepare_tasks(self, tasks: List[str]) -> List[str]:
        """Materialize every task root serially, then let runs use --no-prepare.

        ``prepare.sh`` rewrites the task's own ``work/`` and does
        ``git checkout`` / ``git archive`` in a cache repository shared by every
        task of the same upstream project.  Two concurrent prepares therefore
        race on the same cache checkout even when their task roots differ.
        """
        ready: List[str] = []
        for task in tasks:
            root = self.tasks_root / task
            script = root / "prepare.sh"
            if not script.is_file():
                say(f"PREP  {task} skipped (no prepare.sh)")
                ready.append(task)
                continue
            log_path = self.log_dir / f"prepare_{task}.log"
            say(f"PREP  {task} -> {log_path.name}")
            with log_path.open("w", encoding="utf-8") as log:
                log.write(f"$ bash {script}\n")
                log.flush()
                lock = Path.home() / ".cache" / "migration-bench" / "prepare.lock"
                lock.parent.mkdir(parents=True, exist_ok=True)
                try:
                    rc = subprocess.call(
                        ["flock", str(lock), "bash", str(script)],
                        cwd=str(root),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=self.args.prepare_timeout,
                    )
                except subprocess.TimeoutExpired:
                    rc = 124
            if rc != 0:
                say(f"PREP  {task} FAILED rc={rc}; its jobs are skipped")
            else:
                ready.append(task)
        return ready

    # -- job construction -------------------------------------------------

    def build_jobs(self, tasks: List[str]) -> List[Job]:
        jobs: List[Job] = []
        for task in tasks:
            for arm in self.args.arms:
                for run in range(1, self.args.runs + 1):
                    label = f"{self.args.prefix}_{arm}_{task}" + (f"_r{run}" if self.args.runs > 1 else "")
                    jobs.append(Job(arm=arm, task=task, run=run, label=label,
                                    log=self.log_dir / f"{label}.log"))
        return jobs

    def done(self, job: Job) -> bool:
        attempt = self.report_root / job.label / job.task / f"run{job.run}" / "attempt.json"
        return attempt.is_file()

    def command(self, job: Job) -> List[str]:
        cmd = [
            PY,
            str(BENCH),
            "run",
            "--arm",
            job.arm,
            "--scenario",
            self.args.scenario,
            "--only",
            job.task,
            "--runs",
            "1",
            "--label",
            job.label,
            "--no-prepare",
        ]
        if job.arm == "method":
            cmd += [
                "--method-prompt",
                self.args.method_prompt,
                "--bundle",
                str(self.args.bundle),
                "--method-stage-image",
                self.args.stage_image,
            ]
        return cmd

    # -- scheduling -------------------------------------------------------

    def run_job(self, job: Job) -> None:
        with self.lock:
            job.started_at = time.time()
        cmd = self.command(job)
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        with job.log.open("w", encoding="utf-8") as log:
            log.write("$ " + " ".join(cmd) + "\n")
            log.flush()
            job.proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env)
            rc = job.proc.wait()
        job.finished_at = time.time()
        job.rc = rc
        self.write_state()

    def run(self, jobs: List[Job]) -> int:
        pending = list(jobs)
        running: Dict[str, Job] = {}
        busy_tasks: Dict[str, int] = {}
        failures: List[Job] = []
        total = len(jobs)
        finished = 0

        say(f"batch: {total} jobs, workers={self.args.workers}")
        while pending or running:
            # Fill free slots without starting two jobs for the same task.
            for job in list(pending):
                if len(running) >= self.args.workers:
                    break
                if busy_tasks.get(job.task):
                    continue
                pending.remove(job)
                busy_tasks[job.task] = 1
                self.jobs.append(job)
                thread = threading.Thread(target=self.run_job, args=(job,), daemon=True)
                thread.start()
                running[job.label] = job
                say(f"START {job.label} ({len(running)}/{self.args.workers} running)")
            if not running:
                continue
            time.sleep(2)
            for label, job in list(running.items()):
                if job.finished_at is None:
                    continue
                running.pop(label)
                busy_tasks.pop(job.task, None)
                finished += 1
                verdict = "ok" if job.rc == 0 else f"rc={job.rc}"
                say(f"END   {job.label} {verdict} duration={(job.finished_at - job.started_at):.0f}s "
                    f"[{finished}/{total}]")
                if job.rc != 0:
                    failures.append(job)
                self.write_state()
        say(f"batch done: {total - len(failures)} ok, {len(failures)} failed")
        return 0 if not failures else 1

    # -- state ------------------------------------------------------------

    def write_state(self) -> None:
        rows = []
        for job in self.jobs:
            rows.append(
                {
                    "label": job.label,
                    "arm": job.arm,
                    "task": job.task,
                    "run": job.run,
                    "pid": job.proc.pid if job.proc else None,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "duration_s": (
                        round(job.finished_at - job.started_at, 1)
                        if job.started_at and job.finished_at
                        else None
                    ),
                    "rc": job.rc,
                    "log": str(job.log.relative_to(ROOT)),
                }
            )
        try:
            self.state_path.write_text(json.dumps({"jobs": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


def say(message: str) -> None:
    print(f"[batch] {message}", flush=True)


def read_tasks(args: argparse.Namespace) -> List[str]:
    tasks: List[str] = []
    tasks.extend(args.task or [])
    if args.tasks_file:
        path = Path(args.tasks_file)
        if not path.is_absolute():
            path = ROOT / path
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                tasks.append(line)
    return list(dict.fromkeys(tasks))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", action="append", default=[], help="task id (repeatable)")
    ap.add_argument("--tasks-file", default="", help="one task id per line")
    ap.add_argument("--arms", default="default,method", help="comma-separated arms")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--prefix", default="s1", help="label prefix; also names batch_state_<prefix>.json")
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--method-prompt", default=DEFAULT_METHOD_PROMPT)
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--stage-image", default=DEFAULT_STAGE_IMAGE)
    ap.add_argument("--force", action="store_true", help="rerun jobs that already have attempt.json")
    ap.add_argument("--skip-prepare", action="store_true", help="trust existing task work/ trees")
    ap.add_argument("--skip-preflight", action="store_true", help="do not run tools/preflight_tasks.py first")
    ap.add_argument("--prepare-timeout", type=int, default=1800)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.workers < 1:
        ap.error("--workers must be positive")
    args.arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    tasks = read_tasks(args)
    if not tasks:
        ap.error("give --task or --tasks-file")
    args.bundle = Path(args.bundle)
    if not args.bundle.is_absolute():
        args.bundle = (ROOT / args.bundle).resolve()
    if not (args.bundle / "manifest.json").is_file():
        ap.error(f"bundle has no manifest.json: {args.bundle}")

    batch = Batch(args)
    jobs = batch.build_jobs(tasks)
    if not args.force:
        kept = []
        for job in jobs:
            if batch.done(job):
                say(f"SKIP  {job.label} (attempt.json exists)")
            else:
                kept.append(job)
        jobs = kept
    if args.dry_run:
        for job in jobs:
            say("DRY   " + " ".join(batch.command(job)))
        return 0
    if not jobs:
        say("nothing to do")
        return 0

    needed = list(dict.fromkeys(job.task for job in jobs))
    if not args.skip_preflight:
        # Static checks catch harness defects that would otherwise only show up
        # after a 30-60 minute agent run (missing programs in the target image,
        # a gold answer that trips its own gate, loader paths, port clashes).
        cmd = [PY, str(ROOT / "tools" / "preflight_tasks.py")]
        for task in needed:
            cmd += ["--task", task]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if proc.returncode != 0:
            say("preflight FAILED; not starting any job")
            for line in (proc.stdout + proc.stderr).splitlines():
                say("preflight| " + line)
            return 1
        say(f"preflight ok for {len(needed)} task(s)")
    if not args.skip_prepare:
        # Evaluator answers copied back by an earlier gold run must not sit in
        # the agent-visible work/ tree that --no-prepare reuses.
        subprocess.call(
            [PY, str(ROOT / "tools" / "clean_gold_from_work.py"), "--parent", str(batch.tasks_root)],
            cwd=str(ROOT),
        )
        ready = set(batch.prepare_tasks(needed))
        dropped = [job for job in jobs if job.task not in ready]
        for job in dropped:
            job.note = "prepare failed"
        jobs = [job for job in jobs if job.task in ready]
        if not jobs:
            say("no runnable jobs after preparation")
            return 1

    return batch.run(jobs)


if __name__ == "__main__":
    raise SystemExit(main())