#!/usr/bin/env python3
"""Collect three-arm case evidence from ``reports/bench/<label>/``.

Each bench label directory holds ``<task>/run<N>/attempt.json`` plus, for the
method arm, a staged ``method/tasks/<task>/outputs/full_library/`` tree.  This
tool reads those records and emits one row per run: arm, verdict, build/test
gates, duration, cost counters, and the first failure hint the judge printed.

Usage::

    python3 tools/collect_case_results.py --label default_nginx_proc_r1 \
        --label method_nginx_proc_r1
    python3 tools/collect_case_results.py --prefix nginx_proc --format json
    python3 tools/collect_case_results.py --all --format markdown
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH = ROOT / "reports" / "bench"


def read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def failure_hint(attempt: dict) -> str:
    log = ((attempt.get("judge") or {}).get("report") or {}).get("log") or ""
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    strong = re.compile(r"(=FAIL\b|^\s*FAIL\b|Assertion|No rule to make|undefined reference|fatal error)", re.I)
    weak = re.compile(r"(\bFAIL\b|\bERROR\b|error:|No such file)", re.I)
    noisy = re.compile(r"(error\.log|log tail|^---|^==)", re.I)
    hints = [line for line in lines if strong.search(line)]
    if not hints:
        hints = [line for line in lines if weak.search(line) and not noisy.search(line)]
    if not hints:
        return ""
    # The last strong failure names the probe/assert that decided the run.
    return hints[-1][:220]


def component_ids(attempt: dict, run_dir: Path, task: str) -> List[str]:
    bundle = attempt.get("component_bundle") or {}
    manifest = bundle.get("manifest")
    candidates = []
    if manifest:
        candidates.append(Path(manifest))
    method_root = run_dir / "method" / "tasks" / task
    candidates.extend(
        [
            method_root / "outputs" / "full_library" / "manifest.json",
            method_root / "outputs" / "full_library" / "INDEX.md",
        ]
    )
    for path in candidates:
        data = read_json(path)
        if data and isinstance(data.get("components"), list):
            return [c.get("bundle_id", "") for c in data["components"]]
        if path.suffix == ".md" and path.is_file():
            ids = re.findall(r"`([a-z0-9][a-z0-9-]{12,})`", path.read_text(encoding="utf-8", errors="replace"))
            ids = sorted({i for i in ids if "-" in i})
            if ids:
                return ids
    return []


def row(label: str, task: str, run_dir: Path) -> Optional[dict]:
    attempt = read_json(run_dir / "attempt.json")
    if not attempt:
        return None
    judge = attempt.get("judge") or {}
    report = judge.get("report") or {}
    tokens = attempt.get("agent_tokens") or {}
    return {
        "label": label,
        "task": task,
        "run": attempt.get("run"),
        "arm": attempt.get("arm"),
        "condition": attempt.get("condition"),
        "status": attempt.get("status"),
        "agent_status": attempt.get("agent_status"),
        "build": attempt.get("build"),
        "tests": attempt.get("tests"),
        "regression": attempt.get("regression"),
        "api_removal": attempt.get("api_removal"),
        "target_api": attempt.get("target_api"),
        "duration_s": attempt.get("duration_s"),
        "judge_rc": judge.get("rc"),
        "judge_duration_s": judge.get("duration_s"),
        "model_calls": attempt.get("agent_model_calls"),
        "tool_calls": attempt.get("agent_tool_calls"),
        "tokens_in": tokens.get("input"),
        "tokens_out": tokens.get("output"),
        "profile": attempt.get("dsh_profile"),
        "method_profile": attempt.get("method_profile"),
        "method_prompt_override": (attempt.get("method_prompt_hashes") or {}).get("method_prompt_override"),
        "components": component_ids(attempt, run_dir, task),
        "bundle_sha256": (attempt.get("component_bundle") or {}).get("sha256"),
        "failure_hint": failure_hint(attempt) if attempt.get("status") != "pass" else "",
        "evidence": str((run_dir / "attempt.json").relative_to(ROOT)),
    }


def collect(labels: List[str], bench: Path) -> List[dict]:
    rows: List[dict] = []
    for label in labels:
        label_dir = bench / label
        if not label_dir.is_dir():
            continue
        for task_dir in sorted(p for p in label_dir.iterdir() if p.is_dir()):
            for run_dir in sorted(task_dir.glob("run*")):
                if run_dir.is_dir():
                    item = row(label, task_dir.name, run_dir)
                    if item:
                        rows.append(item)
    return rows


def markdown(rows: List[dict]) -> str:
    header = (
        "| Label | Task | Arm | Result | build | tests | regr | api | target | "
        "Duration s | Model calls | Tokens in/out | Components | Evidence |\n"
        "|---|---|---|---|---|---|---|---|---|---:|---:|---|---|---|"
    )
    lines = [header]
    for r in rows:
        verdict = "PASS" if r["status"] == "pass" else str(r["status"]).upper()
        comps = ", ".join(c.split("-")[-1] for c in r["components"]) or "-"
        tokens = (
            f"{r['tokens_in']}/{r['tokens_out']}" if r["tokens_in"] is not None else "-"
        )
        lines.append(
            f"| {r['label']} | {r['task']} | {r['arm']} | **{verdict}** | {r['build']} | "
            f"{r['tests']} | {r['regression'] or '-'} | {r['api_removal'] or '-'} | "
            f"{r['target_api'] or '-'} | {r['duration_s']} | {r['model_calls']} | {tokens} | "
            f"{comps} | [{Path(r['evidence']).parent.name}/attempt.json]({r['evidence']}) |"
        )
        if r["failure_hint"]:
            lines.append(f"|  |  |  | ↳ `{r['failure_hint']}` |  |  |  |  |  |  |  |  |  |  |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", action="append", default=[], help="bench label directory")
    ap.add_argument("--prefix", help="include labels starting with this prefix")
    ap.add_argument("--all", action="store_true", help="every label under reports/bench")
    ap.add_argument("--bench", default=str(DEFAULT_BENCH))
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = ap.parse_args(argv)

    bench = Path(args.bench)
    if not bench.is_absolute():
        bench = ROOT / bench
    labels = list(args.label)
    if args.prefix or args.all:
        for path in sorted(bench.iterdir()):
            if not path.is_dir():
                continue
            if args.all or path.name.startswith(args.prefix or ""):
                labels.append(path.name)
    if not labels:
        ap.error("give --label, --prefix or --all")

    rows = collect(sorted(dict.fromkeys(labels)), bench)
    if not rows:
        raise SystemExit("no attempt.json found for the requested labels")
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())