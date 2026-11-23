#!/usr/bin/env python3
"""Origin baseline: one context packet, one model call, then judge.

This is deliberately *not* an agent:

1. prepare the task and copy its workspace;
2. package the task spec, file tree and selected source files into one prompt;
3. make exactly one OpenAI-compatible ``/chat/completions`` request;
4. apply the returned file map to the workspace;
5. run the same build/tests/API judge as the other arms.

There is no tool loop, no DSH session, no retry, and no feedback to the model.
The model's single response is accepted as-is and then judged.

Output protocol requested from the model::

    {"files": [{"path": "relative/path", "content": "..."}],
     "delete": ["optional/relative/path"],
     "notes": "optional"}

Only ordinary text files below the workspace root are accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from shared.harness import agent_view, taskmodel  # noqa: E402
import agent_trial as at  # noqa: E402
import migration_trial as bt  # noqa: E402

ORIGIN_SYSTEM = """You are a one-shot software migration assistant.
You have no tools and cannot inspect or execute anything. Everything you know is in the
user message: the task spec, a file tree and selected file contents.

Produce one JSON object only. Do not wrap it in Markdown fences. Do not ask questions.
The schema is:

{"files":[{"path":"relative/path","content":"full file content"}],
 "delete":["optional/relative/path"],
 "notes":"optional short explanation"}

Write complete replacement files, not unified diffs. Paths are relative to the task
workspace. For a negative/non-portable task, write the requested report file instead of
inventing a target implementation. Do not modify build files.
"""

def origin_system_prompt(task: Dict[str, Any]) -> str:
    """Return the target-aware system prompt for the one-shot arm.

    Direct has a scenario-specific system prompt.  Origin previously had only
    the generic one-shot instruction, so a Kylin/IPP model could ignore the
    target platform and submit a portable fallback.  Keep the output contract
    generic but make the target requirement explicit.
    """
    scenario = str(task.get("scenario") or "")
    if scenario == "ipp_to_vsipl":
        target = (
            "You are a software engineer migrating a C/C++ component from Intel IPP to VSIPL (jvsip).\n"
            "The submitted implementation must use the VSIPL C API and link against libvsip; "
            "a portable fallback is not accepted."
        )
    elif scenario == "windows_to_kylin":
        target = (
            "You are a software engineer porting one component to Kylin V10 SP3 with GCC 13.\n"
            "The submitted implementation must use the target Kylin/Linux platform APIs required "
            "by the task; a portable Windows-independent fallback is not accepted."
        )
    else:
        target = "Use the target platform required by the task."
    return target + "\n\n" + ORIGIN_SYSTEM


IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "build", "build-release",
    "cmake-build-debug", "component_bundle", "node_modules", "gold",
    "gold_authored", "dist", "generated", ".cache",
}
TEXT_SUFFIXES = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".py", ".sh",
    ".cmake", ".txt", ".md", ".mk", ".in", ".inc", ".def", ".rc",
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".pc",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        data = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" not in data


def _read_text(path: Path, limit: int) -> Optional[str]:
    try:
        if path.stat().st_size > limit * 8:
            return None
        data = path.read_bytes()
        text = data.decode("utf-8")
        if "\x00" in text:
            return None
        return text[:limit]
    except (OSError, UnicodeDecodeError):
        return None


def _iter_workspace_files(work: Path) -> List[Path]:
    files: List[Path] = []
    if not work.is_dir():
        return files
    for current, dirs, names in os.walk(work):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        base = Path(current)
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            files.append(path)
    return files


def build_context(
    task_root: Path,
    task: Dict[str, Any],
    max_chars: int,
    *,
    work_view: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a deterministic, budgeted context packet.

    Metadata-listed source files and build files are included first, then the
    rest of the workspace in path order. The tree is always included so the
    model knows what exists even when file bodies are truncated.
    """
    # The origin prompt must see the same filtered workspace as an agent, not
    # the evaluator's full work tree.  Callers that already copied a filtered
    # view pass it in; standalone callers get a temporary filtered copy.
    if work_view is not None:
        return _build_context_from_work(Path(work_view), task, max_chars)
    with tempfile.TemporaryDirectory(prefix="origin-view-") as tmp:
        agent_view.copy_agent_view(task_root / "work", Path(tmp), task)
        return _build_context_from_work(Path(tmp), task, max_chars)


def _build_context_from_work(work: Path, task: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    source = task.get("source") or {}
    system = origin_system_prompt(task)
    preferred: List[str] = []
    for key in ("files", "windows_files", "test_files"):
        value = source.get(key) if isinstance(source, dict) else None
        if isinstance(value, str):
            preferred.append(value)
        elif isinstance(value, list):
            preferred.extend(str(item) for item in value)
    preferred += ["TASK.md", "README.md", "CMakeLists.txt", "Makefile", "configure"]
    all_files = _iter_workspace_files(work)
    by_rel = {_rel(p, work): p for p in all_files}
    ordered: List[str] = []
    for rel in preferred:
        rel = rel.strip().lstrip("./")
        if rel and rel in by_rel and rel not in ordered:
            ordered.append(rel)
    # Build files next, then source-like files.
    for p in all_files:
        rel = _rel(p, work)
        if rel not in ordered and "/" not in rel and p.name in {
            "CMakeLists.txt", "Makefile", "makefile", "configure",
            "configure.ac", "meson.build", "BUILD", "BUILD.bazel",
        }:
            ordered.append(rel)
    # Do not add the whole repository.  One-shot origin has no tools/feedback;
    # dumping every text file makes the request enormous and still leaves the
    # model to guess which files matter.  ``preferred`` already contains the
    # task's source/windows/test files; build files were added above.

    tree_all = [rel for rel in sorted(by_rel)]
    # The tree is useful orientation, but a 700-file repository can consume
    # more context than the code itself.  Keep a bounded tree alongside the
    # selected file bodies.
    tree_limit = 200
    tree_lines = tree_all[:tree_limit]
    if len(tree_all) > tree_limit:
        tree_lines.append(f"... ({len(tree_all) - tree_limit} more paths omitted)")
    chunks: List[str] = []
    used = 0
    included: List[str] = []
    omitted: List[str] = []
    for rel in ordered:
        text = _read_text(by_rel[rel], 120_000)
        if text is None:
            continue
        header = f"\n--- FILE: {rel} ---\n"
        if used + len(header) + len(text) > max_chars:
            omitted.append(rel)
            continue
        chunks.append(header + text)
        used += len(header) + len(text)
        included.append(rel)

    build_meta = dict(task.get("build") or {})
    build_meta["command"] = taskmodel.agent_build_command(task) or build_meta.get("command", "")
    task_meta = json.dumps(
        {
            "task_id": task.get("task_id") or task.get("id"),
            "scenario": task.get("scenario"),
            "level": task.get("level"),
            "fit": task.get("fit"),
            "title": task.get("title"),
            "target": task.get("target"),
            "build": build_meta,
            "negative": task.get("negative"),
            # Hidden test cases and gate regexes are evaluator-only.
        },
        ensure_ascii=False,
        indent=2,
    )
    spec = str(task.get("spec") or "").strip()
    prompt = "\n".join(
        [
            "You are given one migration task. There is no tool loop: return the complete files now.",
            "",
            "## TASK METADATA",
            task_meta,
            "",
            "## TASK SPEC",
            spec,
            "",
            "## WORKSPACE FILE TREE",
            "\n".join(tree_lines) if tree_lines else "(empty)",
            "",
            "## SELECTED FILE CONTENTS",
            "".join(chunks) if chunks else "(no files selected)",
            "",
            "## CONTEXT NOTE",
            f"Selected {len(included)} files, {used} characters. "
            f"Omitted {len(omitted)} files because of the context budget.",
            "",
            "## OUTPUT CONTRACT",
            system,
        ]
    )
    return {
        "prompt": prompt,
        "tree": tree_lines,
        "included": included,
        "omitted": omitted,
        "chars": len(prompt),
        "content_chars": used,
        "system": system,
    }


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response contains no JSON object")
    value = json.loads(text[start : end + 1], strict=False)
    if not isinstance(value, dict):
        raise ValueError("response JSON is not an object")
    return value


def _safe_relative(path: str) -> Path:
    raw = str(path).replace("\\", "/").lstrip("/")
    if raw.startswith("workspace/"):
        raw = raw[len("workspace/") :]
    elif raw.startswith("work/"):
        # The context describes the workspace as the task package's work/.
        raw = raw[len("work/") :]
    result = Path(raw)
    if not raw or result.is_absolute() or any(part in {"", ".", ".."} for part in result.parts):
        raise ValueError(f"unsafe path: {path!r}")
    return result


def apply_response(workspace: Path, response: str) -> List[str]:
    data = _extract_json(response)
    files = data.get("files") or []
    deletes = data.get("delete") or []
    if not isinstance(files, list) or not isinstance(deletes, list):
        raise ValueError("files/delete must be arrays")
    root = workspace.resolve()
    written: List[str] = []
    for item in files:
        if not isinstance(item, dict) or "path" not in item or "content" not in item:
            raise ValueError("each file needs path and content")
        rel = _safe_relative(str(item["path"]))
        destination = (root / rel).resolve()
        if root not in destination.parents and destination != root:
            raise ValueError(f"path escapes workspace: {item['path']!r}")
        if not isinstance(item["content"], str):
            raise ValueError(f"content is not text: {item['path']!r}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(item["content"], encoding="utf-8")
        written.append(rel.as_posix())
    for raw in deletes:
        rel = _safe_relative(str(raw))
        destination = (root / rel).resolve()
        if root not in destination.parents and destination != root:
            raise ValueError(f"delete path escapes workspace: {raw!r}")
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
            written.append("DELETE " + rel.as_posix())
    return written


def call_chat(
    *,
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout: int,
    system_prompt: str = ORIGIN_SYSTEM,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    url = api_base.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw[:2000]}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"request failed: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(f"response is not JSON: {raw[:1000]}") from exc
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"response has no choices: {raw[:1000]}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError(f"response has no text content: {raw[:1000]}")
    usage = payload.get("usage") or {}
    meta = {
        "duration_s": round(time.time() - started, 1),
        "usage": {
            "input": int(usage.get("prompt_tokens") or 0),
            "output": int(usage.get("completion_tokens") or 0),
        },
        "response_id": payload.get("id"),
        "finish_reason": choices[0].get("finish_reason"),
    }
    return content, meta, payload


def _judge(
    *,
    scenario: str,
    image: str,
    workspace: Path,
    task_root: Path,
    timeout: int,
    tag: str,
    vsipl_root: str,
) -> Dict[str, Any]:
    if scenario == "ipp_to_vsipl":
        return bt._judge_local(
            image,
            workspace,
            task_root,
            timeout=timeout,
            tag=tag,
            env={"VSIPL_ROOT": "/opt/vsipl"},
            mounts=[(Path(vsipl_root).expanduser().resolve(), "/opt/vsipl")],
        )
    if scenario == "windows_to_kylin":
        return at._judge(
            image=image,
            workspace=workspace,
            task_root=task_root,
            timeout=timeout,
            tag=tag,
        )
    raise RuntimeError(f"origin baseline does not support scenario: {scenario}")


def _iter_roots(args: argparse.Namespace) -> List[Path]:
    return at._iter_task_roots(args)


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", action="append", default=[])
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--level", action="append", default=[])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--label", default="origin")
    parser.add_argument("--report-dir", default=None)
    parser.add_argument("--workspace-root", default=None)
    parser.add_argument("--repository-root", default=str(ROOT.parent))
    parser.add_argument("--api-base", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--context-window", type=int, default=262144)
    parser.add_argument("--origin-max-output-tokens", type=int, default=65536,
                        help="output budget for the single origin response (reasoning + JSON)")
    parser.add_argument("--origin-context-chars", type=int, default=200000)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--prepare-timeout", type=int, default=1800)
    parser.add_argument("--judge-timeout", type=int, default=2400)
    parser.add_argument("--ipp-image", default=bt.IPP_IMAGE_DEFAULT)
    parser.add_argument("--kylin-image", default=bt.KYLIN_IMAGE_DEFAULT)
    parser.add_argument("--vsipl-root", default=bt.VSIPL_ROOT_DEFAULT)
    parser.add_argument("--fake-response", default="",
                        help="read one saved response instead of calling the model (self-test)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.task_root and not args.parent:
        if args.only:
            args.parent = ["v1/ipp_vsipl_tasks", "v1/windows_to_kylin/tasks", "v1/cuda_to_musa/tasks"]
        else:
            parser.error("give --task-root, --parent, or --only")
    roots = _iter_roots(args)
    if not roots:
        print("no task packages found", file=sys.stderr)
        return 3
    if any(str(taskmodel.load_task(r).get("scenario")) == "cuda_to_musa" for r in roots):
        print("ERROR origin baseline currently supports ipp_to_vsipl and windows_to_kylin only",
              file=sys.stderr)
        return 2
    if any(str(taskmodel.load_task(r).get("scenario")) == "ipp_to_vsipl" for r in roots) and not args.vsipl_root:
        print("ERROR ipp_to_vsipl needs --vsipl-root or VSIPL_ROOT", file=sys.stderr)
        return 2

    creds = at._resolve_credentials(args)
    api_base, api_key, model = creds["api_base"], creds["api_key"], creds["model"]
    if not args.fake_response and not (api_base and api_key and model):
        print("ERROR origin needs a model credential or --fake-response", file=sys.stderr)
        return 2

    report_dir = Path(args.report_dir or f"reports/origin/{args.label}")
    if not report_dir.is_absolute():
        report_dir = ROOT / report_dir
    workspace_root = Path(args.workspace_root or report_dir / "workspaces")
    report_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for root in roots:
        task = taskmodel.load_task(root)
        task_id = taskmodel.task_id(task)
        scenario = str(task.get("scenario") or "")
        ok, prep_log = at._prepare(root, args.prepare_timeout, False)
        if not ok:
            record = {
                "task": task_id, "scenario": scenario, "arm": "origin",
                "condition": "origin_one_shot", "level": task.get("level"),
                "run": 1, "status": "error", "agent_status": "PrepareError",
                "detail": "prepare.sh failed", "log": prep_log[-4000:],
                "started_at": _now(), "finished_at": _now(),
            }
            results.append(record)
            _write_json(report_dir / task_id / "run1" / "attempt.json", record)
            print(f"ERROR {task_id}: prepare.sh failed", file=sys.stderr)
            continue
        reference = root / "work"
        image = args.ipp_image if scenario == "ipp_to_vsipl" else args.kylin_image
        for run in range(1, args.runs + 1):
            tag = f"{task_id}-r{run}"
            attempt_dir = report_dir / task_id / f"run{run}"
            workspace = workspace_root / tag
            attempt_dir.mkdir(parents=True, exist_ok=True)
            started = time.time()
            record: Dict[str, Any] = {
                "task": task_id,
                "scenario": scenario,
                "arm": "origin",
                "condition": "origin_one_shot",
                "level": task.get("level"),
                "run": run,
                "started_at": _now(),
                "label": args.label,
                "model": model,
                "context_window": args.context_window,
                "max_output_tokens": args.origin_max_output_tokens,
                "status": "error",
                "agent_status": "OneShot",
                "agent_error": None,
                "agent_model_calls": 0,
                "agent_tokens": {"input": 0, "output": 0},
                "build": None,
                "tests": None,
                "api_removal": None,
                "target_api": None,
                "judge": None,
                "detail": "",
            }
            if args.dry_run:
                record["status"] = "skip"
                record["detail"] = "dry-run"
                results.append(record)
                print(f"DRY  {tag}")
                continue
            try:
                at._copy_workspace(reference, workspace, image, task)
                ctx = build_context(root, task, args.origin_context_chars, work_view=workspace)
                (attempt_dir / "prompt.txt").write_text(ctx["prompt"], encoding="utf-8")
                record["origin"] = {
                    "context_chars": ctx["chars"],
                    "context_files": len(ctx["included"]),
                    "omitted_files": len(ctx["omitted"]),
                    "prompt_sha256": hashlib.sha256(ctx["prompt"].encode()).hexdigest(),
                    "system_sha256": hashlib.sha256(ctx["system"].encode()).hexdigest(),
                }
                if args.fake_response:
                    response = Path(args.fake_response).read_text(encoding="utf-8")
                    meta = {"duration_s": 0, "usage": {"input": 0, "output": 0}}
                else:
                    response, meta, _payload = call_chat(
                        api_base=api_base, api_key=api_key, model=model,
                        prompt=ctx["prompt"], max_tokens=args.origin_max_output_tokens,
                        timeout=args.timeout,
                    )
                    record["agent_model_calls"] = 1
                    record["agent_tokens"] = meta["usage"]
                    record.setdefault("origin", {})["finish_reason"] = meta.get("finish_reason")
                (attempt_dir / "response.txt").write_text(response, encoding="utf-8")
                written = apply_response(workspace, response)
                record["origin"]["files_written"] = written
                if not at._chown(image, workspace)[0]:
                    raise RuntimeError("cannot chown workspace for judge")
                judge = _judge(
                    scenario=scenario, image=image, workspace=workspace,
                    task_root=root, timeout=args.judge_timeout, tag=tag,
                    vsipl_root=args.vsipl_root,
                )
                record["judge"] = judge
                report = judge.get("report") or {}
                record["build"] = report.get("build")
                record["tests"] = report.get("tests")
                record["api_removal"] = report.get("api_removal")
                record["target_api"] = report.get("target_api")
                record["status"] = "pass" if (judge.get("rc") == 0 and report.get("status") == "pass") else "fail"
                record["finished_at"] = _now()
                record["duration_s"] = round(time.time() - started, 1)
            except Exception as exc:  # noqa: BLE001
                record["status"] = "error"
                record["agent_status"] = "OneShotError"
                record["agent_error"] = str(exc)[:4000]
                record["finished_at"] = _now()
                record["duration_s"] = round(time.time() - started, 1)
            results.append(record)
            _write_json(attempt_dir / "attempt.json", record)
            print(
                f"{record['status'].upper():5} {tag:<34} "
                f"calls={record.get('agent_model_calls')} "
                f"build={record.get('build')} tests={record.get('tests')} "
                f"api={record.get('api_removal')}"
            )

    counts = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    for record in results:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    summary = {
        "label": args.label, "arm": "origin", "condition": "origin_one_shot",
        "model": model, "context_window": args.context_window,
        "max_output_tokens": args.origin_max_output_tokens,
        "origin_context_chars": args.origin_context_chars,
        "tasks": [r["task"] for r in results], "runs_per_task": args.runs,
        "counts": counts, "results": results,
        "finished_at": _now(),
    }
    _write_json(report_dir / "summary.json", summary)
    print(
        f"SUMMARY pass={counts['pass']} fail={counts['fail']} "
        f"error={counts['error']} skip={counts['skip']}"
    )
    return 0 if counts["pass"] == len(results) and counts["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
