#!/usr/bin/env python3
"""Check that every task package still points at a real upstream pin.

For each task this verifies:

* ``task_id`` matches its directory and the scenario is known;
* ``source.repo`` / ``source.commit`` agree with ``provenance.json``;
* the commit exists in the repository;
* the declared tag (if any) points at that commit;
* every file listed in ``provenance.json`` (source, gold, spec, test,
  reference, remove) exists at that commit;
* ``prepare.sh`` names the same repository and commit;
* a materialized ``work/`` records the same commit and does not leak gold;
* a materialized ``gold/`` actually holds the declared gold files.

No compiler and no target hardware are needed.  Network access is needed
for the default mode; ``--offline`` restricts the check to the local cache.

Usage::

    python3 tools/check_pins.py
    python3 tools/check_pins.py --parent v1/windows_to_kylin/tasks --parent v1/cuda_to_musa/tasks
    python3 tools/check_pins.py --offline --json
    python3 tools/check_pins.py --strict          # warnings become failures

Exit codes: 0 = all pins verified, 1 = at least one broken pin,
2 = at least one pin could not be verified (offline / network / cache miss).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness import taskmodel  # noqa: E402

SCENARIOS = {"ipp_to_vsipl", "windows_to_kylin", "cuda_to_musa", "cuda_to_ascend"}
HEX = re.compile(r"^[0-9a-fA-F]{7,40}$")
URL_RE = re.compile(r"^(https?://|git@|ssh://)")
GLOB_CHARS = set("*?[")

DEFAULT_PARENTS = (
    "v1/ipp_vsipl_tasks",
    "v1/cuda_to_musa/tasks",
    "v3/windows_to_kylin/tasks",
)

FILE_KEYS = (
    "source_files",
    "gold_files",
    "spec_files",
    "test_files",
    "reference_files",
    "remove",
)


class GitError(RuntimeError):
    pass


def _run(cmd: Sequence[str], *, timeout: int = 600) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _cache_root(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = os.environ.get("MIGRATION_BENCH_CACHE")
    if base:
        return Path(base).expanduser().resolve() / "pins"
    return Path.home() / ".cache" / "migration-bench" / "pins"


def _repo_dir(cache: Path, url: str) -> Path:
    slug = re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1])
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", slug)[:40] or "repo"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return cache / f"{slug}-{digest}"


def _ensure_repo(cache: Path, url: str) -> Tuple[Optional[Path], str]:
    repo = _repo_dir(cache, url)
    if (repo / "HEAD").is_file() and (repo / "config").is_file():
        return repo, ""
    repo.parent.mkdir(parents=True, exist_ok=True)
    rc, out = _run(["git", "init", "--bare", str(repo)], timeout=120)
    if rc != 0:
        return None, out
    rc, out = _run(["git", "-C", str(repo), "remote", "add", "origin", url], timeout=60)
    if rc != 0:
        return None, out
    return repo, ""


def _has_commit(repo: Path, sha: str) -> bool:
    rc, _ = _run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"], timeout=60)
    return rc == 0


def _fetch_commit(repo: Path, sha: str, *, timeout: int) -> Tuple[bool, str]:
    if _has_commit(repo, sha):
        return True, "already cached"
    attempts = (
        ["fetch", "--depth", "1", "--filter=blob:none", "origin", sha],
        ["fetch", "--depth", "1", "origin", sha],
        ["fetch", "origin", sha],
    )
    last = ""
    for args in attempts:
        rc, out = _run(["git", "-C", str(repo), *args], timeout=timeout)
        last = out
        if rc == 0 and _has_commit(repo, sha):
            return True, "fetched"
    return False, last


def _paths_at(repo: Path, sha: str, *, timeout: int) -> Tuple[Optional[Set[str]], str]:
    rc, out = _run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", sha],
        timeout=timeout,
    )
    if rc != 0:
        return None, out
    return {item for item in out.split("\0") if item}, ""


def _tag_target(url: str, tag: str, *, timeout: int) -> Tuple[Optional[str], str]:
    rc, out = _run(
        [
            "git",
            "ls-remote",
            "--tags",
            url,
            f"refs/tags/{tag}",
            f"refs/tags/{tag}^{{}}",
        ],
        timeout=timeout,
    )
    if rc != 0:
        return None, out
    direct: Optional[str] = None
    peeled: Optional[str] = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref.endswith("^{}"):
            peeled = sha
        elif ref == f"refs/tags/{tag}":
            direct = sha
    return (peeled or direct), ""


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


def _is_synthetic(repo: str, commit: str) -> bool:
    return (not URL_RE.match(repo)) or commit.lower().startswith("synthetic")


def _match_path(tree: Set[str], path: str, subdir: Optional[str]) -> bool:
    """Return True when ``path`` exists in the commit's file list."""
    candidates = [path]
    if subdir:
        sub = subdir.rstrip("/")
        if not path.startswith(sub + "/"):
            candidates.append(f"{sub}/{path}")

    for candidate in candidates:
        if any(ch in candidate for ch in GLOB_CHARS):
            if any(fnmatch.fnmatch(item, candidate) for item in tree):
                return True
            continue
        if candidate in tree:
            return True
        prefix = candidate.rstrip("/") + "/"
        if any(item.startswith(prefix) for item in tree):
            return True
    return False


def _suggest_paths(tree: Set[str], path: str, subdir: Optional[str], limit: int = 3) -> List[str]:
    """Suggest near matches for a path that no longer exists upstream."""
    base = Path(path).name
    stem = Path(path).stem
    exact = sorted(item for item in tree if Path(item).name == base)
    if exact:
        return exact[:limit]
    for needle in (base.lower(), stem.lower()):
        loose = sorted(item for item in tree if needle and needle in item.lower())
        if loose:
            return loose[:limit]
    return []


class TaskReport:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.task = root.name
        self.scenario: Optional[str] = None
        self.level: Optional[str] = None
        self.repo: str = ""
        self.commit: str = ""
        self.tag: Optional[str] = None
        self.materialized = False
        self.gold_present = False
        self.judge_only = False
        self.checks: List[Dict[str, str]] = []
        self.detail_lines: List[str] = []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append({"name": name, "status": status, "detail": detail})

    def status(self) -> str:
        statuses = {check["status"] for check in self.checks}
        if "fail" in statuses:
            return "fail"
        if statuses == {"skip"}:
            return "skip"
        if "unknown" in statuses:
            return "unknown"
        if "warn" in statuses:
            return "warn"
        if statuses == {"synthetic"}:
            return "synthetic"
        return "ok"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "scenario": self.scenario,
            "level": self.level,
            "repo": self.repo,
            "commit": self.commit,
            "tag": self.tag,
            "materialized": self.materialized,
            "gold_present": self.gold_present,
            "judge_only": self.judge_only,
            "status": self.status(),
            "checks": self.checks,
        }


def _check_declarations(
    root: Path,
    prov: Dict[str, Any],
    src: Dict[str, Any],
    report: TaskReport,
    scenario: Optional[str],
) -> None:
    """Check provenance/task.yaml agreement and the prepare.sh recipe."""
    for key in ("repo", "commit", "license"):
        left = prov.get(key)
        right = src.get(key)
        if left and right and left != right:
            report.add(f"provenance.{key}", "fail", f"{left!r} != {right!r}")
    if prov.get("license") or src.get("license"):
        report.add("provenance", "ok")

    prepare = root / "prepare.sh"
    if prepare.is_file():
        text = prepare.read_text(encoding="utf-8", errors="replace")
        missing = []
        if report.repo not in text:
            missing.append("repo URL")
        if report.commit not in text:
            missing.append("commit")
        if missing:
            report.add("prepare.sh", "fail", "does not name " + ", ".join(missing))
        else:
            report.add("prepare.sh", "ok")
    elif scenario in {"windows_to_kylin", "cuda_to_musa", "cuda_to_ascend"}:
        report.add("prepare.sh", "fail", "missing prepare.sh")
    else:
        report.add("prepare.sh", "skip", "not required for this scenario")


def _check_task(root: Path, opts: argparse.Namespace, report: TaskReport) -> None:
    try:
        task = taskmodel.load_task(root)
    except Exception as exc:  # noqa: BLE001 - report parse errors
        report.add("task.yaml", "fail", f"cannot parse: {exc}")
        return

    prov = _load_provenance(root)
    src = task.get("source") or {}

    report.scenario = task.get("scenario")
    report.level = task.get("level")
    report.repo = str(prov.get("repo") or src.get("repo") or "")
    report.commit = str(prov.get("commit") or src.get("commit") or "")
    report.tag = prov.get("tag") or src.get("tag")
    if report.tag:
        report.tag = str(report.tag)

    if task.get("task_id") and str(task["task_id"]) != root.name:
        report.add("task_id", "fail", f"'{task['task_id']}' != directory '{root.name}'")
    else:
        report.add("task_id", "ok")

    if report.scenario not in SCENARIOS:
        report.add("scenario", "fail", f"unknown scenario: {report.scenario!r}")
    else:
        report.add("scenario", "ok")

    if not report.repo:
        report.add("repo", "fail", "source.repo is missing")
        return
    if not report.commit:
        report.add("commit", "fail", "source.commit is missing")
        return

    if src.get("vendored") or prov.get("vendored"):
        report.add("repo", "local", report.repo)
        report.add("commit", "local", f"vendored snapshot @ {report.commit}")
        report.add("upstream", "skip", "vendored snapshot: no upstream fetch")
        _check_declarations(root, prov, src, report, report.scenario)
        _check_local_only(root, task, prov, opts, report)
        return

    if _is_synthetic(report.repo, report.commit):
        report.add("repo", "synthetic", report.repo)
        report.add("commit", "synthetic", report.commit)
        report.add("upstream", "skip", "synthetic task: no upstream pin to verify")
        _check_declarations(root, prov, src, report, report.scenario)
        _check_local_only(root, task, prov, opts, report)
        return

    if not URL_RE.match(report.repo):
        report.add("repo", "fail", f"not a URL: {report.repo!r}")
        return
    report.add("repo", "ok", report.repo)

    if not HEX.match(report.commit):
        report.add("commit", "fail", f"not a hex SHA: {report.commit!r}")
        return
    if len(report.commit) != 40:
        report.add("commit", "warn", f"short SHA ({len(report.commit)}): {report.commit}")

    _check_declarations(root, prov, src, report, report.scenario)

    if opts.offline:
        cache_repo = _repo_dir(opts.cache, report.repo)
        if not _has_commit(cache_repo, report.commit):
            report.add("upstream", "unknown", f"offline and not cached: {cache_repo}")
            _check_local_only(root, task, prov, opts, report)
            return
    else:
        cache_repo, err = _ensure_repo(opts.cache, report.repo)
        if cache_repo is None:
            report.add("upstream", "unknown", err or "cannot create git cache")
            _check_local_only(root, task, prov, opts, report)
            return
        ok, detail = _fetch_commit(cache_repo, report.commit, timeout=opts.timeout)
        if not ok:
            report.add("commit", "unknown", f"cannot fetch {report.commit}: {detail[-400:]}")
            _check_local_only(root, task, prov, opts, report)
            return
        report.add("commit", "ok", report.commit)

    tree, err = _paths_at(cache_repo, report.commit, timeout=opts.timeout)
    if tree is None:
        report.add("files", "unknown", f"cannot list tree: {err[-400:]}")
        _check_local_only(root, task, prov, opts, report)
        return

    if report.tag and not opts.no_tag:
        tag_sha, err = _tag_target(report.repo, report.tag, timeout=opts.timeout)
        if tag_sha is None:
            report.add("tag", "warn", f"cannot resolve tag '{report.tag}': {err[-200:]}")
        elif tag_sha.lower() != report.commit.lower():
            report.add(
                "tag",
                "fail",
                f"tag '{report.tag}' -> {tag_sha}, task pins {report.commit}",
            )
        else:
            report.add("tag", "ok", report.tag)

    subdir = prov.get("subdir") or src.get("subdir")
    subdir = str(subdir) if subdir else None
    total = 0
    missing_paths: List[str] = []
    for key in FILE_KEYS:
        values = _as_list(prov.get(key) or src.get(key))
        # task.yaml stores the remove list under prepare.remove.
        if key == "remove" and not values:
            values = _as_list((task.get("prepare") or {}).get("remove"))
        for rel in values:
            total += 1
            if not _match_path(tree, rel, subdir):
                suggestions = _suggest_paths(tree, rel, subdir)
                hint = f" (maybe: {', '.join(suggestions)})" if suggestions else ""
                missing_paths.append(f"{key}: {rel}{hint}")
    if missing_paths:
        shown = missing_paths[: opts.max_details]
        more = len(missing_paths) - len(shown)
        detail = "; ".join(shown)
        if more > 0:
            detail += f" (+{more} more)"
        report.add("files", "fail", detail)
    else:
        report.add("files", "ok", f"{total} declared paths exist at the commit")

    _check_local_only(root, task, prov, opts, report)


def _check_local_only(
    root: Path,
    task: Dict[str, Any],
    prov: Dict[str, Any],
    opts: argparse.Namespace,
    report: TaskReport,
) -> None:
    """Checks that do not need the upstream checkout."""
    src = task.get("source") or {}
    gold_files = _as_list(prov.get("gold_files") or src.get("gold_files"))
    gold_kind = prov.get("gold_kind") or task.get("gold_kind")
    negative = bool(task.get("negative"))

    work = root / "work"
    gold = root / "gold"
    work_files = [p for p in work.rglob("*") if p.is_file()] if work.is_dir() else []
    report.materialized = bool(work_files)
    report.judge_only = bool(gold_files) is False and not negative

    if work_files:
        marker = work / ".source_commit"
        if marker.is_file():
            recorded = marker.read_text(encoding="utf-8", errors="replace").strip()
            if recorded and report.commit and recorded != report.commit:
                report.add("work.commit", "fail", f"{recorded} != {report.commit}")
            elif recorded:
                report.add("work.commit", "ok", recorded)
        else:
            report.add("work.commit", "warn", "materialized work/ has no .source_commit")
    else:
        report.add("work", "skip", "not materialized (run prepare.sh)")

    if gold_files and not negative:
        if not gold.is_dir():
            report.add("gold", "skip", "gold/ not materialized (run prepare.sh)")
        else:
            actual = {
                str(p.relative_to(gold))
                for p in gold.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            }
            names = {Path(item).name for item in actual}

            def _present(rel: str) -> bool:
                if rel in actual or Path(rel).name in names:
                    return True
                # A declared directory gold (src/os/unix, src/util/unix) is
                # present when at least one file under it was materialized.
                prefix = rel.rstrip("/") + "/"
                return any(item.startswith(prefix) for item in actual)

            found = 0
            for rel in gold_files:
                if _present(rel):
                    found += 1
            report.gold_present = found == len(gold_files)
            if found == len(gold_files):
                report.add("gold", "ok", f"{found} gold file(s) present")
            else:
                missing = [rel for rel in gold_files if not _present(rel)]
                report.add(
                    "gold",
                    "warn",
                    "missing gold: " + "; ".join(missing[: opts.max_details]),
                )

            # The agent-visible tree must not contain the gold implementation.
            # The declared gold path is always a leak if present.  For files
            # that merely share a basename, compare content with the
            # materialized gold: porting tasks legitimately ship the Windows
            # counterpart under the same name (libuv's src/win/thread.c next
            # to the gold src/unix/thread.c), and flagging those by name
            # alone produces a false positive.
            leaked = []
            if work.is_dir():
                for rel in gold_files:
                    exact = work / rel
                    if exact.is_file():
                        leaked.append(str(exact.relative_to(root)))
                    elif exact.is_dir():
                        leaked.extend(
                            str(p.relative_to(root))
                            for p in exact.rglob("*")
                            if p.is_file()
                        )
                gold_digests: Dict[str, set] = {}
                if gold.is_dir():
                    for rel in gold_files:
                        g = gold / rel
                        files = (
                            [g]
                            if g.is_file()
                            else [p for p in g.rglob("*") if p.is_file()]
                            if g.is_dir()
                            else []
                        )
                        for item in files:
                            gold_digests.setdefault(item.name, set()).add(
                                hashlib.sha256(item.read_bytes()).hexdigest()
                            )
                for path in work.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = str(path.relative_to(root))
                    if rel in leaked:
                        continue
                    digests = gold_digests.get(path.name)
                    if digests and hashlib.sha256(path.read_bytes()).hexdigest() in digests:
                        leaked.append(rel)
            if leaked:
                report.add(
                    "gold.leak",
                    "fail",
                    "gold file visible in work/: " + "; ".join(leaked[: opts.max_details]),
                )
            else:
                report.add("gold.leak", "ok")

    if gold_kind in {"none"} or negative:
        report.add("gold.kind", "skip", f"gold_kind={gold_kind or 'none'}")
    elif not gold_files:
        report.add("gold.kind", "skip", "no gold file declared (judge-only task)")


def _iter_roots(parents: Iterable[str], opts: argparse.Namespace) -> List[Path]:
    roots: List[Path] = []
    for parent in parents:
        path = Path(parent)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_dir():
            continue
        for child in sorted(path.iterdir()):
            if child.is_dir() and (child / "task.yaml").is_file():
                roots.append(child)
    if opts.only:
        wanted = set(opts.only)
        roots = [root for root in roots if root.name in wanted]
    if opts.level:
        levels = {level.upper() for level in opts.level}
        kept = []
        for root in roots:
            try:
                task = taskmodel.load_task(root)
                if str(task.get("level", "")).upper() in levels:
                    kept.append(root)
            except Exception:  # noqa: BLE001 - keep so the failure is reported
                kept.append(root)
        roots = kept
    return roots


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--parent",
        action="append",
        default=[],
        help="directory containing task packages (repeatable)",
    )
    ap.add_argument("--only", action="append", default=[], help="only these task ids")
    ap.add_argument(
        "--level",
        action="append",
        default=[],
        help="only tasks at this level (L1/L2/L3, repeatable)",
    )
    ap.add_argument("--cache", default=None, help="git cache root")
    ap.add_argument("--offline", action="store_true", help="do not touch the network")
    ap.add_argument("--no-tag", action="store_true", help="skip tag resolution")
    ap.add_argument("--strict", action="store_true", help="warnings are failures")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--max-details", type=int, default=8)
    args = ap.parse_args(argv)

    parents = args.parent or list(DEFAULT_PARENTS)
    args.cache = _cache_root(args.cache)
    args.cache.mkdir(parents=True, exist_ok=True)

    roots = _iter_roots(parents, args)
    if not roots:
        print("no task packages found", file=sys.stderr)
        return 3

    started = time.time()
    reports: List[TaskReport] = []
    for root in roots:
        report = TaskReport(root)
        _check_task(root, args, report)
        reports.append(report)
        status = report.status()
        if status == "fail" or (args.strict and status == "warn"):
            mark = "FAIL"
        elif status == "unknown":
            mark = "UNKN"
        elif status == "warn":
            mark = "WARN"
        elif status == "synthetic":
            mark = "SYNT"
        elif status == "skip":
            mark = "SKIP"
        else:
            mark = "OK  "
        if args.json:
            continue
        detail = ""
        bad = [
            check
            for check in report.checks
            if check["status"] in ({"fail", "unknown"} | ({"warn"} if args.strict else set()))
        ]
        if bad:
            detail = "  " + " | ".join(
                f"{check['name']}: {check['detail']}" for check in bad[: args.max_details]
            )
        print(
            f"{mark} {report.task:<32} {report.scenario or '-':<16} "
            f"{(report.level or '-'):<3}{detail}"
        )

    summary = {"ok": 0, "warn": 0, "fail": 0, "unknown": 0, "skip": 0, "synthetic": 0}
    for report in reports:
        summary[report.status()] = summary.get(report.status(), 0) + 1
    materialized = sum(1 for report in reports if report.materialized)
    gold_present = sum(1 for report in reports if report.gold_present)
    judge_only = sum(1 for report in reports if report.judge_only)
    failed = summary["fail"] > 0 or (args.strict and summary["warn"] > 0)
    unknown = summary["unknown"] > 0

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not failed and not unknown,
                    "summary": summary,
                    "materialized": materialized,
                    "gold_present": gold_present,
                    "judge_only": judge_only,
                    "elapsed_s": round(time.time() - started, 1),
                    "cache": str(args.cache),
                    "tasks": [report.as_dict() for report in reports],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(
            "SUMMARY "
            + " ".join(f"{key}={value}" for key, value in summary.items())
            + f" materialized={materialized} gold_present={gold_present}"
            + f" judge_only={judge_only} elapsed={time.time() - started:.1f}s"
            + f" cache={args.cache}"
        )
        if failed:
            print("RESULT=FAIL (fix the broken pins before running gold sanity)")
        elif unknown:
            print("RESULT=UNKNOWN (some pins could not be verified; rerun online)")
        else:
            print("RESULT=PASS")

    if failed:
        return 1
    if unknown:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())