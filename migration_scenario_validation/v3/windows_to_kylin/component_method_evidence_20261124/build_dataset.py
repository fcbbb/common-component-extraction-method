#!/usr/bin/env python3
"""Build the 20-task component-method evidence dataset.

Reads benchmark reports from reports/bench and writes an aggregated,
self-contained dataset under this directory.  Existing results are only
read, never modified.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .../migration_scenario_validation
BENCH = ROOT / "reports" / "bench"
WORKSPACES = BENCH / "workspaces"
DATA = HERE / "data"
SOURCES = DATA / "sources"
CASES = HERE / "cases"

# (task, category, default_label, method_label, notes)
TASKS = [
    # method wins
    ("synthetic_posix_fs_requests", "method_win", "s2v2_default_synthetic3", "s2v2_method_synthetic3", ""),
    ("synthetic_spawn_event_loop", "method_win", "s2v3_default_spawn", "s2v3_method_spawn",
     "default 失败基于补强后的探针；旧探针下 default 曾 PASS。"),
    ("synthetic_thread_runtime", "method_win", "s2v2_default_synthetic3", "s2v2_method_synthetic3", ""),
    ("l2_opencv_highgui", "method_win", "s1_default_l2_opencv_highgui", "s1_method_l2_opencv_highgui",
     "default 失败含环境因素：IPPICV/ADE 下载失败、numpy 缺失、2400s 超时；证据强度弱于三个合成题。"),
    # default win
    ("v2_nginx_full", "default_win", "s1_default_v2_nginx_full", "s1_method_v2_nginx_full",
     "method 仅有 batch 日志 rc=1，无 attempt.json；运行时选中 2 个组件。"),
    # both fail
    ("negative_win32_eventlog", "both_fail", "s1_default_negative_win32_eventlog", "s1_method_negative_win32_eventlog",
     "第 20 个特殊项：负向对照，method 检索判定“无组件适用”本身正确，但编排层按 ERROR 中止，未产出报告。"),
    ("v2_file", "both_fail", "s1_default_v2_file", "s1g_method_v2_file", ""),
    ("v2_foundation_full", "both_fail", "s1_default_v2_foundation_full", "s1_method_v2_foundation_full", ""),
    ("v2_libgit2_util_full", "both_fail", "s1_default_v2_libgit2_util_full", "s1_method_v2_libgit2_util_full", ""),
    ("v2_nginx_files", "both_fail", "s1_default_v2_nginx_files", "s1g_method_v2_nginx_files", ""),
    ("v2_nginx_process", "both_fail", "default_nginx_proc_r1", "method_nginx_proc_r1", ""),
    ("v2_poco_process", "both_fail", "default_poco_proc_r1", "method_poco_proc_r1", ""),
    ("v3_poco_fs_stack", "both_fail", "s1_default_v3_poco_fs_stack", "s1g_method_v3_poco_fs_stack", ""),
    # both pass
    ("v2_curl_tls", "both_pass", "s1_default_v2_curl_tls", "s1_method_v2_curl_tls", ""),
    ("v2_rwlock_semaphore", "both_pass", "s1_default_v2_rwlock_semaphore", "s1_method_v2_rwlock_semaphore", ""),
    ("v2_thread", "both_pass", "s1_default_v2_thread", "s1_method_v2_thread", ""),
    ("v2_curl_file", "both_pass", "s1b_default_v2_curl_file", "s1g_method_v2_curl_file", ""),
    ("v2_curl_thread", "both_pass", "s1d_default_v2_curl_thread", "s1d_method_v2_curl_thread", ""),
    ("v2_nginx_thread", "both_pass", "default_nginx_thread_r1", "method_nginx_thread_r1", ""),
    ("synthetic_multi_call_site", "both_pass", "s1e_default_synthetic_multi_call_site", "s1h_method_synthetic_multi_call_site", ""),
]

# Batch-log facts for runs that produced no attempt.json.
NO_ATTEMPT = {
    ("s1_method_v2_nginx_full", "v2_nginx_full"): {
        "status": "fail",
        "duration_s": 1009.0,
        "gate_status": "unknown (no attempt.json)",
        "failure_summary": "batch runner rc=1，无 attempt.json（运行在生成报告前中止）",
        "evidence": "B (batch log only)",
    }
}

CASE_TASKS = [
    "synthetic_posix_fs_requests",
    "synthetic_spawn_event_loop",
    "synthetic_thread_runtime",
    "l2_opencv_highgui",
    "negative_win32_eventlog",
    "v2_nginx_full",
    "v2_file",
    "v2_foundation_full",
]

PROBE_KEYS = (
    "AFS_DEEP=", "SPL_DEEP=", "THR_DEEP=", "AFS_PROBE=", "SPL_PROBE=", "THR_PROBE=",
    "deep:", "!!!FAILURES!!!", "FAILURE", "There was", "There were", "failure", "Failure",
    "FAIL ", "FAIL:", "fail:", "sensitivity:", "error", "Error", "timed out",
    "timeout after", "Traceback", "terminate called", "ModuleNotFoundError",
    "Download failed", "api_removal", "source_hits", "_MSC_VER",
)


def normalize(text: str) -> str:
    if not text:
        return ""
    return text.replace("\\n", "\n").replace("\\t", "\t")


def attempt_path(label: str, task: str) -> Path | None:
    runs = sorted((BENCH / label / task).glob("run*/attempt.json"))
    return runs[-1] if runs else None


def gate_status(attempt: dict) -> str:
    parts = []
    for key in ("build", "tests", "api_removal", "target_api"):
        value = attempt.get(key)
        if isinstance(value, dict):
            value = value.get("status", "")
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def _is_build_noise(line: str) -> bool:
    return (
        line.startswith(("cc ", "gmake", "make[", "[ ", "[", "-e ", "./configure",
                         "sed ", "rm ", "cp ", "cmake ", "cd ", "{",
                         '"api_removal":', '"source_regex":', '"source_hits":',
                         '"match":', '"errors":', '"symbols":', '"positive":',
                         '"expect_fail":', '"exclude_globs":'))
        or "Building C" in line or "Linking " in line or "Built target" in line
        or "%%" in line
    )


def _api_removal_hit(tail: str) -> str:
    lines = [line.strip() for line in tail.splitlines()]
    for index, line in enumerate(lines):
        if line == '"match": "_MSC_VER"' or '"_MSC_VER"' in line and '"match"' in line:
            file_name = ""
            line_no = ""
            for back in range(index - 1, max(index - 6, -1), -1):
                if lines[back].startswith('"file":'):
                    file_name = lines[back].split(":", 1)[1].strip().strip('",')
                if lines[back].startswith('"line":'):
                    line_no = lines[back].split(":", 1)[1].strip().strip('",')
            if file_name:
                return f"api_removal hit: {file_name}:{line_no} (_MSC_VER)"
    return ""


def failure_summary(attempt: dict, status: str) -> str:
    if status == "pass":
        return ""
    detail = (attempt.get("detail") or attempt.get("agent_error") or "").strip()
    judge = attempt.get("judge") or {}
    tail = normalize(judge.get("log_tail") or "")
    picked: list[str] = []
    for line in tail.splitlines():
        line = line.strip()
        if not line or _is_build_noise(line):
            continue
        if any(key in line for key in PROBE_KEYS):
            if line not in picked:
                picked.append(line)
    picked = picked[-12:]
    parts = []
    gates = gate_status(attempt)
    if gates:
        parts.append(gates)
    if detail:
        parts.append(detail)
    hit = _api_removal_hit(tail)
    if hit:
        parts.append(hit)
    if picked:
        parts.append(" | ".join(picked))
    text = " || ".join(parts)
    return text[:1100]


def selection(label: str, task: str) -> list[str]:
    candidates = sorted(WORKSPACES.glob(f"{label}/{task}-r*/component_bundle/selection.json"))
    if not candidates:
        candidates = sorted(WORKSPACES.glob(f"{label}/{task}/run*/component_bundle/selection.json"))
    if not candidates:
        return []
    try:
        payload = json.loads(candidates[-1].read_text())
        return list(payload.get("selected_bundle_ids") or [])
    except Exception:
        return []


def load_attempt(label: str, task: str) -> dict:
    path = attempt_path(label, task)
    if not path:
        return {}
    return json.loads(path.read_text())


def record(task: str, category: str, arm: str, label: str, notes: str) -> dict:
    attempt = load_attempt(label, task)
    if not attempt:
        override = NO_ATTEMPT.get((label, task), {})
        return {
            "task": task, "category": category, "arm": arm, "label": label,
            "status": override.get("status", "missing"),
            "duration_s": override.get("duration_s", ""),
            "agent_status": "", "build": "", "tests": "", "judge_rc": "",
            "gate_status": override.get("gate_status", ""),
            "evidence": override.get("evidence", "missing"),
            "selected_components": ";".join(selection(label, task)),
            "failure_summary": override.get("failure_summary", "no attempt.json"),
            "notes": notes,
            "started_at": "", "finished_at": "",
            "attempt_path": "",
        }
    judge = attempt.get("judge") or {}
    status = attempt.get("status", "")
    build = attempt.get("build")
    if isinstance(build, dict):
        build = build.get("status", "")
    tests = attempt.get("tests")
    if isinstance(tests, dict):
        tests = tests.get("status", "")
    return {
        "task": task, "category": category, "arm": arm, "label": label,
        "status": status,
        "duration_s": attempt.get("duration_s", ""),
        "agent_status": attempt.get("agent_status", ""),
        "build": build or "",
        "tests": tests or "",
        "judge_rc": judge.get("rc", ""),
        "gate_status": gate_status(attempt),
        "evidence": "A (attempt.json)",
        "selected_components": ";".join(selection(label, task)),
        "failure_summary": failure_summary(attempt, status),
        "notes": notes,
        "started_at": attempt.get("started_at", ""),
        "finished_at": attempt.get("finished_at", ""),
        "attempt_path": str(attempt_path(label, task).relative_to(ROOT)) if attempt_path(label, task) else "",
    }


def copy_sources(rows: list[dict]) -> None:
    for row in rows:
        label = row["label"]
        task = row["task"]
        src_attempt = attempt_path(label, task)
        dst_dir = SOURCES / label
        dst_dir.mkdir(parents=True, exist_ok=True)
        summary = BENCH / label / "summary.json"
        if summary.exists():
            shutil.copy2(summary, dst_dir / "summary.json")
        if src_attempt:
            dst_task = dst_dir / "attempts" / task
            dst_task.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_attempt, dst_task / "attempt.json")
        sel = sorted(WORKSPACES.glob(f"{label}/{task}-r*/component_bundle/selection.json"))
        if not sel:
            sel = sorted(WORKSPACES.glob(f"{label}/{task}/run*/component_bundle/selection.json"))
        if sel:
            dst_task = dst_dir / "selections" / task
            dst_task.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sel[-1], dst_task / "selection.json")


def write_cases(rows: list[dict]) -> None:
    CASES.mkdir(parents=True, exist_ok=True)
    by_task: dict[str, list[dict]] = {}
    for row in rows:
        by_task.setdefault(row["task"], []).append(row)
    for task in CASE_TASKS:
        out = []
        for row in sorted(by_task.get(task, []), key=lambda r: r["arm"]):
            out.append(f"===== {row['arm']} | label={row['label']} | status={row['status']} | duration={row['duration_s']}s")
            if row["selected_components"]:
                out.append(f"selected_components: {row['selected_components']}")
            out.append(f"failure_summary: {row['failure_summary'] or '(none)'}")
            path = attempt_path(row["label"], task)
            if path:
                attempt = json.loads(path.read_text())
                judge = attempt.get("judge") or {}
                tail = normalize(judge.get("log_tail") or "")
                if tail:
                    out.append("----- judge log tail (last 5000 chars) -----")
                    out.append(tail[-5000:])
                else:
                    out.append("(no judge log tail)")
            else:
                out.append("(no attempt.json)")
            out.append("")
        (CASES / f"{task}.txt").write_text("\n".join(out))


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "attempts").mkdir(exist_ok=True)
    if SOURCES.exists():
        shutil.rmtree(SOURCES)
    SOURCES.mkdir(parents=True)

    rows: list[dict] = []
    for task, category, default_label, method_label, notes in TASKS:
        rows.append(record(task, category, "default", default_label, notes))
        rows.append(record(task, category, "method", method_label, notes))

    copy_sources(rows)

    long_fields = [
        "task", "category", "arm", "label", "status", "duration_s", "agent_status",
        "build", "tests", "judge_rc", "gate_status", "evidence", "selected_components",
        "failure_summary", "notes", "started_at", "finished_at", "attempt_path",
    ]
    with (DATA / "results_long.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=long_fields)
        writer.writeheader()
        writer.writerows(rows)

    wide_fields = [
        "task", "category",
        "default_label", "default_status", "default_duration_s", "default_gates", "default_failure",
        "method_label", "method_status", "method_duration_s", "method_gates", "method_components",
        "method_failure", "method_selected", "evidence_default", "evidence_method", "notes",
    ]
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        grouped.setdefault(row["task"], {})[row["arm"]] = row
    wide_rows = []
    for task, category, _, _, notes in TASKS:
        d = grouped[task]["default"]
        m = grouped[task]["method"]
        wide_rows.append({
            "task": task, "category": category,
            "default_label": d["label"], "default_status": d["status"],
            "default_duration_s": d["duration_s"], "default_gates": d["gate_status"], "default_failure": d["failure_summary"],
            "method_label": m["label"], "method_status": m["status"],
            "method_duration_s": m["duration_s"], "method_gates": m["gate_status"], "method_components": len([c for c in m["selected_components"].split(";") if c]) if m["selected_components"] else 0,
            "method_failure": m["failure_summary"], "method_selected": m["selected_components"],
            "evidence_default": d["evidence"], "evidence_method": m["evidence"], "notes": notes,
        })
    with (DATA / "results_wide.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=wide_fields)
        writer.writeheader()
        writer.writerows(wide_rows)

    categories = Counter(row["category"] for row in rows if row["arm"] == "default")
    default_pass = sum(1 for row in rows if row["arm"] == "default" and row["status"] == "pass")
    method_pass = sum(1 for row in rows if row["arm"] == "method" and row["status"] == "pass")
    method_wins = [row["task"] for row in rows if row["arm"] == "method" and row["status"] == "pass"
                   and next(r for r in rows if r["task"] == row["task"] and r["arm"] == "default")["status"] != "pass"]
    default_wins = [row["task"] for row in rows if row["arm"] == "default" and row["status"] == "pass"
                    and next(r for r in rows if r["task"] == row["task"] and r["arm"] == "method")["status"] != "pass"]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_count": len(TASKS),
        "categories": dict(categories),
        "default_pass": default_pass,
        "method_pass": method_pass,
        "method_wins": method_wins,
        "default_wins": default_wins,
        "strict_method_pass_default_not_pass": len(method_wins),
        "model": "DeepSeek-V4.1-Flash-1017",
        "default_profile": "component-method (baseline_direct)",
        "method_profile": "component-method-migration",
        "method_prompt": "config/prompts/method_retrieval_only_system.txt",
        "bundle": "v3/windows_to_kylin/library_generated/full_20261123/library",
        "stage_image": "migration/kylin:sp3-p2",
        "notes": [
            "第 20 个任务 negative_win32_eventlog 是负向对照：method 的检索结论正确，但流程按 ERROR 中止，不计 PASS。",
            "v2_nginx_full 的 method 结果只有 batch rc=1，没有 attempt.json。",
            "l2_opencv_highgui 的 default 失败含环境因素（网络下载、numpy、超时）。",
            "已排除三个明显错误的 method ERROR：v2_path、v2_shared_library、v2_curl_build。",
        ],
    }
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (DATA / "results.json").write_text(json.dumps({
        "summary": summary,
        "tasks": wide_rows,
        "attempts": rows,
    }, indent=2, ensure_ascii=False) + "\n")

    write_cases(rows)

    print("wrote", HERE)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()