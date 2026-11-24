#!/usr/bin/env python3
"""Lint the migration datasets for agent-visible judge/test leakage."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness import agent_prompt, taskmodel  # noqa: E402

PATTERNS = {
    "ipp_to_vsipl": r"vsip_|jvsip",
    "cuda_to_musa": r"load_inline|musa_sources|__global__|<<<|torch_musa",
    "windows_to_kylin": r"pthread_[A-Za-z0-9_]+|dlopen|dlsym|dlclose|OpenSSL|GTK|epoll|fork/exec",
}


def _parents() -> List[Path]:
    return [
        ROOT / "v1" / "ipp_vsipl_tasks",
        ROOT / "v3" / "ipp_vsipl" / "tasks",
        ROOT / "v1" / "cuda_to_musa" / "tasks",
        ROOT / "v3" / "cuda_to_musa" / "tasks",
        ROOT / "v3" / "windows_to_kylin" / "tasks",
    ]


# The prompt is the only task text the agent sees.  These markers must never
# reach it: dataset identity, provenance, and anything that names the
# evaluator or its hidden material.
PROMPT_META = r"(?i)(scenario\s*:|level\s*:|source repository|family\s*:|sequence\s*:)"
PROMPT_JUDGE = r"(?i)\b(hidden|evaluator|judge|eval_single_runner|fail_to_pass|pass_to_pass)\b"


def lint_prompt(task: Dict[str, Any], root: Path) -> List[str]:
    """Render the actual prompt and reject metadata/judge leakage."""
    errors: List[str] = []
    try:
        prompt = agent_prompt.render_task_prompt(task, root=root)
    except Exception as exc:  # noqa: BLE001 - report a broken renderer
        return [f"cannot render agent prompt: {exc}"]
    meta = sorted(set(m.group(0).lower() for m in re.finditer(PROMPT_META, prompt)))
    if meta:
        errors.append(f"agent prompt contains dataset metadata: {meta}")
    judge = sorted(set(m.group(0).lower() for m in re.finditer(PROMPT_JUDGE, prompt)))
    if judge:
        errors.append(f"agent prompt names judge material: {judge}")
    scenario = str(task.get("scenario") or "")
    if scenario and scenario in prompt:
        errors.append(f"agent prompt contains scenario id: {scenario}")
    source = task.get("source") or {}
    repo = str(source.get("repo") or "")
    commit = str(source.get("commit") or "")
    if repo and repo in prompt:
        errors.append(f"agent prompt contains source repo: {repo}")
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit or "") and (
        commit in prompt or commit[:12] in prompt
    ):
        errors.append(f"agent prompt contains source commit: {commit}")
    return errors


def lint_v2_identifiers(task: Dict[str, Any], root: Path, spec: str) -> List[str]:
    """Reject V2 spec references to APIs the agent cannot see.

    The V2 spec points at the public headers instead of restating their
    semantics.  A typo or a stale API name then becomes a contradiction
    between the prompt and the workspace, so check every ``Poco::X`` and
    ``x()`` the spec names against the materialized tree.
    """
    if not taskmodel.task_id(task).startswith("v2_"):
        return []
    work = root / "work"
    include = work / "Foundation" / "include"
    poco = include / "Poco"
    if not poco.is_dir():
        return []  # recipe-only task, nothing to check against yet
    errors: List[str] = []
    for name in sorted(set(re.findall(r"\bPoco::([A-Za-z_]\w*)", spec))):
        if not (poco / f"{name}.h").is_file():
            errors.append(f"spec names Poco::{name}, but Poco/{name}.h is not visible")
    for name in sorted(set(re.findall(r"`Poco/([A-Za-z_]\w*)\.h`", spec))):
        if not (poco / f"{name}.h").is_file():
            errors.append(f"spec names Poco/{name}.h, which is not visible")
    headers = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in include.rglob("*.h")
    )
    for name in sorted(set(re.findall(r"\b([a-z][A-Za-z0-9_]*)\(\)", spec))):
        if not re.search(rf"\b{re.escape(name)}\s*\(", headers):
            errors.append(f"spec names {name}(), which no visible header declares")
    return errors


def lint_task(root: Path) -> Dict[str, Any]:
    task = taskmodel.load_task(root)
    task_id = taskmodel.task_id(task)
    scenario = str(task.get("scenario") or "")
    errors: List[str] = []
    spec = str(task.get("spec") or "")
    pattern = PATTERNS.get(scenario)
    if pattern:
        hits = sorted(set(re.findall(pattern, spec)))
        if hits:
            errors.append(f"visible spec contains target hint(s): {hits}")
    judge_words = sorted(set(re.findall(r"hidden|evaluator|eval_single_runner|nginx-tests", spec, re.I)))
    if judge_words:
        errors.append(f"visible spec names judge material: {judge_words}")
    readme = root / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace")
        if "## Hidden tests" in text:
            errors.append("README.md contains ## Hidden tests")
        if any(token in text for token in ("TASK.md", "hidden_tests")):
            errors.append("README.md mentions an agent-visible TASK/hidden test")
    work_task = root / "work" / "TASK.md"
    if work_task.exists():
        errors.append("work/TASK.md is agent-visible")
    errors.extend(lint_prompt(task, root))
    errors.extend(lint_v2_identifiers(task, root, spec))
    return {"task": task_id, "scenario": scenario, "ok": not errors, "errors": errors}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    results = []
    for parent in _parents():
        if not parent.is_dir():
            continue
        for path in sorted(parent.glob("*/task.yaml")):
            results.append(lint_task(path.parent))
    ok = all(item["ok"] for item in results)
    if args.json:
        print(json.dumps({"ok": ok, "tasks": results}, indent=2, ensure_ascii=False))
    else:
        for item in results:
            print(("OK  " if item["ok"] else "FAIL") + f" {item['scenario']:<16} {item['task']}")
            for error in item["errors"]:
                print(f"     ERROR {error}")
        print(f"LINT={'PASS' if ok else 'FAIL'} tasks={len(results)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
