#!/usr/bin/env python3
"""P2 agent trial: let the DeepSeek Harness (DSH) attempt one task, then judge it.

The P0/P1 controls answer "is the task package correct?".  This script answers
the P2 question: "can an agent actually do the task, and does the judge score
the attempt?".

Wiring (one attempt):

1. ``prepare.sh`` materializes the upstream snapshot into ``<task>/work``
   (gold stays in ``<task>/gold`` and never enters the agent workspace).
2. The work tree is copied to a per-attempt directory and bind-mounted into a
   throw-away container of the target image with ``--network none``.
3. ``DshHeadlessBackend`` (the same backend the component-method pipeline uses,
   ``@deepseek-ai/dsh`` 0.2.2-rc.1 with the pinned ``controlled-bash`` plugin)
   runs the agent against that container.  The only tool is
   ``controlled_bash``; the agent finishes by printing the completion marker.
4. The container is removed and the workspace is judged by
   ``shared/harness/runner.py`` in a *fresh* container of the same image,
   exactly like the gold positive control.

Every attempt writes a JSON record as soon as it is final, so a WSL restart or
Docker failure does not lose finished attempts.

Usage::

    python3 tools/agent_trial.py \
        --parent windows_to_kylin/tasks \
        --only l1_poco_thread --only l2_libuv_thread \
        --runs 3 --label p2_kylin

    # plumbing self-test without any model credential or cost
    python3 tools/agent_trial.py --only l1_poco_thread --runs 1 \
        --fake-model --label p2_selftest

Exit codes: 0 = every judged attempt passed, 1 = at least one attempt failed
the judge, 2 = setup error (missing credential, Docker, package, ...).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.harness import taskmodel  # noqa: E402

COMPLETION_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
AGENT_UID = 10001


def _resource_args() -> List[str]:
    """Cgroup limits so a runaway build cannot OOM the WSL VM."""
    memory = os.environ.get("MIGRATION_CONTAINER_MEMORY", "4g")
    cpus = os.environ.get("MIGRATION_CONTAINER_CPUS", "4")
    return [
        "--memory", memory,
        "--memory-swap", memory,
        "--cpus", cpus,
        "--pids-limit", "2048",
        "-e", "CMAKE_BUILD_PARALLEL_LEVEL=2",
        "-e", "MAKEFLAGS=-j2",
        "-e", "NINJAFLAGS=-j2",
    ]
ACTIVATION = (
    "export PATH=/opt/rh/gcc-toolset-13/root/usr/bin:$PATH; "
    "export LD_LIBRARY_PATH=/opt/rh/gcc-toolset-13/root/usr/lib64:/opt/gcc13-libs"
)
SYSTEM_PROMPT = f"""You are a software engineer porting one component to Kylin V10 SP3 with GCC 13.
Use the controlled_bash tool for every inspection, edit, and build command; you have no other tool.
The task workspace is /workspace and it is the repository root. Use /tmp/build as the build directory.
External network access is disabled: every source file you need is already present, and no package
can be downloaded. The implementation you are asked to write was removed from /workspace and does
not exist anywhere else in this container, so do not search the filesystem for a copy; write it. Modify only files under /workspace. Do not modify or disable tests, build files,
or evaluator inputs, and do not special-case test names to fake behavior.
When the implementation is complete and the build command succeeds, call controlled_bash once with
cwd /workspace and a command whose first non-empty output line is exactly {COMPLETION_MARKER}."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    cmd: List[str],
    *,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return 124, f"timeout after {timeout}s\n{out}"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _load_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def _resolve_credentials(args: argparse.Namespace) -> Dict[str, str]:
    repo = Path(args.repository_root).expanduser().resolve()
    dotenv = _load_env_file(repo / ".env")
    # repository/.env is the project-owned route and wins over an inherited
    # shell export: this box exports a stale aliyun token-plan route in
    # ~/.bashrc that is out of quota, while .env points at the working route.
    api_key = args.api_key or dotenv.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    api_base = (
        args.api_base
        or dotenv.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_API_BASE", "")
    )
    model = args.model or dotenv.get("MODEL_NAME") or os.environ.get("MODEL_NAME", "")
    if model.startswith("openai/"):
        model = model[len("openai/") :]
    return {
        "api_key": api_key,
        "api_base": api_base.rstrip("/"),
        "model": model,
        "repository_root": str(repo),
    }


def _iter_task_roots(args: argparse.Namespace) -> List[Path]:
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
            except Exception:  # noqa: BLE001
                continue
            if str(task.get("level", "")).upper() in levels:
                kept.append(root)
        roots = kept
    seen = set()
    unique: List[Path] = []
    for root in roots:
        key = root.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _task_prompt(task: Dict[str, Any], root: Path) -> str:
    spec = str(task.get("spec") or "").strip()
    source = task.get("source") or {}
    build = taskmodel.command_of(task, "build") or ""
    build = taskmodel.expand_command(
        build, root=root, work=Path("/workspace"), build=Path("/tmp/build"),
        golden=Path("/workspace"),
    )
    lines = [
        f"# {task.get('title') or taskmodel.task_id(task)}",
        "",
        f"Scenario: {task.get('scenario')}    Level: {task.get('level')}",
        f"Source repository: {source.get('repo', '')} @ {source.get('commit', '')}",
        "",
        spec,
        "",
        "## Workspace",
        "",
        "The repository snapshot is at /workspace. The reference implementation was removed;",
        "other platform backends and the public headers are still present for orientation.",
        "",
        "## Build command",
        "",
        "The evaluator runs this exact command from /workspace:",
        "",
        "```bash",
        build,
        "```",
        "",
        "Build into /tmp/build as shown. Hidden behavior tests and an API-removal gate are",
        "evaluated after you finish; they are not visible in the workspace.",
        "",
        f"When the build succeeds, submit with: echo {COMPLETION_MARKER}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _prepare(task_root: Path, timeout: int, no_prepare: bool) -> Tuple[bool, str]:
    prepare = task_root / "prepare.sh"
    if not prepare.is_file():
        return True, "no prepare.sh"
    work = task_root / "work"
    if no_prepare and work.is_dir() and any(work.iterdir()):
        return True, "reused existing work/ (--no-prepare)"
    rc, out = _run(["bash", str(prepare)], cwd=task_root, timeout=timeout)
    return rc == 0, out[-4000:]


def _remove_tree(path: Path, image: str) -> None:
    """Remove a previous attempt workspace, which is owned by uid 10001.

    The workspace is chowned to the agent uid before the agent runs, so the
    host user cannot delete it directly.  Delete it from a root container.
    """
    if not path.exists():
        return
    rc, _ = _run(
        [
            "docker", "run", "--rm", "--user", "0",
            "-v", f"{path.parent}:/p",
            "--entrypoint", "rm",
            image, "-rf", f"/p/{path.name}",
        ],
        timeout=300,
    )
    if rc != 0:
        shutil.rmtree(path, ignore_errors=True)


def _copy_workspace(source: Path, target: Path, image: str) -> None:
    _remove_tree(target, image)
    shutil.copytree(source, target, symlinks=True)
    for path in target.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o644 if not os.access(path, os.X_OK) else 0o755)


def _chown(image: str, workspace: Path) -> Tuple[bool, str]:
    rc, out = _run(
        [
            "docker", "run", "--rm", "--user", "0",
            "-v", f"{workspace}:/workspace",
            "--entrypoint", "chown",
            image, "-R", f"{AGENT_UID}:{AGENT_UID}", "/workspace",
        ],
        timeout=300,
    )
    return rc == 0, out


def _start_container(image: str, workspace: Path, name: str) -> Tuple[bool, str]:
    rc, out = _run(
        [
            "docker", "run", "-d", "--name", name,
            "--network", "none",
            *_resource_args(),
            "-v", f"{workspace}:/workspace",
            "-w", "/workspace",
            "--entrypoint", "sleep",
            image, "infinity",
        ],
        timeout=300,
    )
    return rc == 0, out.strip()


def _stop_container(name: str) -> None:
    _run(["docker", "rm", "-f", name], timeout=120)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Return the runner's top-level report.

    ``runner.py`` prints one JSON object, but its nested ``api_detail`` also
    carries a ``status`` key; picking the last ``status`` dict grabbed that
    nested object and lost ``build``/``tests``.  The top-level report is the
    one that also has ``build_dir``.
    """
    decoder = json.JSONDecoder()
    reports: List[Dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "status" in value:
            reports.append(value)
    for report in reports:
        if "build_dir" in report and "task" in report:
            return report
    return reports[-1] if reports else None


def _judge(
    *,
    image: str,
    workspace: Path,
    task_root: Path,
    timeout: int,
    tag: str,
) -> Dict[str, Any]:
    rel = task_root.resolve().relative_to(ROOT).as_posix()
    name = f"p2-judge-{tag}-{uuid.uuid4().hex[:8]}"
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        *_resource_args(),
        "--user", f"{AGENT_UID}:{AGENT_UID}",
        "-e", "HOME=/tmp",
        "-e", "PYTHONUNBUFFERED=1",
        "-v", f"{ROOT}:/bench:ro",
        "-v", f"{workspace}:/workspace",
        "-w", "/bench",
        image,
        "python3", "/bench/shared/harness/runner.py",
        "--task-root", f"/bench/{rel}",
        "--work-dir", "/workspace",
        "--build-dir", f"/tmp/judge-build-{tag}",
        "--timeout", str(timeout),
    ]
    started = time.time()
    rc, out = _run(cmd, timeout=timeout + 300)
    parsed = _extract_json(out)
    return {
        "rc": rc,
        "duration_s": round(time.time() - started, 1),
        "report": parsed,
        "log_tail": out[-6000:],
    }


# ``tool`` selects which shell tool the fixture drives: the container arm uses
# ``controlled_bash``; a host-side profile uses the stock ``bash`` tool.
_FAKE_STATE: Dict[str, Any] = {"n": 0, "tool": "controlled_bash"}


def _fake_shell_arguments(command: str) -> Dict[str, Any]:
    cwd = str(_FAKE_STATE.get("cwd") or "/workspace")
    if _FAKE_STATE.get("tool") == "bash":
        return {"command": command, "workdir": cwd, "description": "run fixture command"}
    return {"command": command, "cwd": cwd, "timeout_seconds": 30}


class _FakeModelHandler(BaseHTTPRequestHandler):
    """Deterministic OpenAI-compatible stream: inspect, then submit."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        _FAKE_STATE["n"] += 1
        number = _FAKE_STATE["n"]
        if number == 1:
            tool_call = {
                "index": 0,
                "id": "call-inspect",
                "type": "function",
                "function": {
                    "name": str(_FAKE_STATE.get("tool") or "controlled_bash"),
                    "arguments": json.dumps(_fake_shell_arguments("ls -la; pwd")),
                },
            }
            finish = "tool_calls"
            content = None
        elif number == 2:
            tool_call = {
                "index": 0,
                "id": "call-submit",
                "type": "function",
                "function": {
                    "name": str(_FAKE_STATE.get("tool") or "controlled_bash"),
                    "arguments": json.dumps(
                        _fake_shell_arguments(f"echo {COMPLETION_MARKER}")
                    ),
                },
            }
            finish = "tool_calls"
            content = None
        else:
            tool_call = None
            finish = "stop"
            content = "fixture complete"
        delta: Dict[str, Any] = {"role": "assistant"}
        if content is not None:
            delta["content"] = content
        if tool_call is not None:
            delta["tool_calls"] = [tool_call]
        chunks = [
            {
                "id": f"chatcmpl-{number}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-{number}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            },
        ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _start_fake_model(tool: str = "controlled_bash") -> Tuple[ThreadingHTTPServer, threading.Thread, str]:
    _FAKE_STATE["n"] = 0
    _FAKE_STATE["tool"] = tool
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}/v1"


def _image_id(image: str) -> Optional[str]:
    rc, out = _run(["docker", "inspect", "--format", "{{.Id}}", image], timeout=60)
    return out.strip() if rc == 0 else None


def _diff_workspace(reference: Path, workspace: Path, out: Path) -> None:
    rc, out_text = _run(
        ["diff", "-ruN", "--exclude=build", str(reference), str(workspace)],
        timeout=600,
    )
    out.write_text(out_text, encoding="utf-8", errors="replace")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", action="append", default=[])
    ap.add_argument("--parent", action="append", default=[])
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--level", action="append", default=[])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--label", default="p2")
    ap.add_argument("--image", default="migration/kylin:sp3-p2")
    ap.add_argument("--report-dir", default=None)
    ap.add_argument("--workspace-root", default=None)
    ap.add_argument("--repository-root", default=str(ROOT.parent))
    ap.add_argument("--api-base", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--fake-model", action="store_true", help="local fixture model, no cost")
    ap.add_argument("--prepare-timeout", type=int, default=1800)
    ap.add_argument("--no-prepare", action="store_true")
    ap.add_argument("--command-timeout", type=int, default=600)
    ap.add_argument("--total-timeout", type=int, default=5400)
    ap.add_argument("--step-limit", type=int, default=150)
    ap.add_argument("--context-window", type=int, default=131072)
    ap.add_argument("--max-output-tokens", type=int, default=32768)
    ap.add_argument("--judge-timeout", type=int, default=2400)
    ap.add_argument("--keep-containers", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.task_root and not args.parent:
        ap.error("give --task-root or --parent")
    roots = _iter_task_roots(args)
    if not roots:
        print("no task packages found", file=sys.stderr)
        return 3

    report_dir = Path(args.report_dir or f"reports/agent_trial/{args.label}")
    if not report_dir.is_absolute():
        report_dir = ROOT / report_dir
    workspace_root = Path(args.workspace_root or report_dir / "workspaces")
    report_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    creds = _resolve_credentials(args)
    server = thread = None
    api_base = creds["api_base"]
    api_key = creds["api_key"]
    model = creds["model"]
    if args.fake_model:
        server, thread, api_base = _start_fake_model()
        api_key, model = "fixture-key", "fixture-model"
    elif not (api_base and api_key and model):
        print(
            "ERROR no model credential: set OPENAI_API_BASE / OPENAI_API_KEY / MODEL_NAME, "
            f"fill {creds['repository_root']}/.env, or pass --fake-model",
            file=sys.stderr,
        )
        return 2

    repo = Path(creds["repository_root"])
    if str(repo / "src") not in sys.path:
        sys.path.insert(0, str(repo / "src"))
    from component_method.agent_runtime.contracts import AgentRunRequest
    from component_method.agent_runtime.dsh_headless import DshHeadlessBackend

    try:
        backend = DshHeadlessBackend(
            api_key=api_key,
            base_url=api_base,
            repository_root=repo,
            runtime_activation=ACTIVATION,
            context_window=args.context_window,
            max_output_tokens=args.max_output_tokens,
            host_environment=(
                {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
                if args.fake_model
                else None
            ),
        )
        backend.validate_runtime()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR DSH runtime is not usable: {exc}", file=sys.stderr)
        if server is not None:
            server.shutdown()
            server.server_close()
        return 2

    identity = backend.runtime_identity()
    print(f"dsh={identity.get('dsh_version')} node={identity.get('node_version')} model={model}")
    print(f"api={api_base} image={args.image} tasks={len(roots)} runs={args.runs}")

    results: List[Dict[str, Any]] = []
    for root in roots:
        task = taskmodel.load_task(root)
        task_id = taskmodel.task_id(task)
        ok, prep_log = _prepare(root, args.prepare_timeout, args.no_prepare)
        if not ok:
            print(f"ERROR {task_id}: prepare.sh failed", file=sys.stderr)
            results.append({"task": task_id, "status": "error", "detail": "prepare.sh failed"})
            continue
        reference = root / "work"

        for run in range(1, args.runs + 1):
            tag = f"{task_id}-r{run}"
            attempt_dir = report_dir / task_id / f"run{run}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            workspace = workspace_root / tag
            record: Dict[str, Any] = {
                "task": task_id,
                "scenario": task.get("scenario"),
                "level": task.get("level"),
                "run": run,
                "started_at": _now(),
                "label": args.label,
                "model": model,
                "dsh_runtime": identity,
                "status": "error",
                "agent_status": None,
                "agent_error": None,
                "judge": None,
                "detail": "",
            }
            if args.dry_run:
                record["status"] = "skip"
                record["detail"] = "dry-run"
                results.append(record)
                print(f"DRY  {tag}")
                continue

            started = time.time()
            try:
                _copy_workspace(reference, workspace, args.image)
            except OSError as exc:
                record["detail"] = f"cannot copy workspace: {exc}"
                results.append(record)
                print(f"ERROR {tag}: cannot copy workspace: {exc}")
                continue
            ok, out = _chown(args.image, workspace)
            if not ok:
                record["detail"] = f"chown failed: {out[-500:]}"
                results.append(record)
                print(f"ERROR {tag}: chown failed")
                continue

            container = f"p2-agent-{uuid.uuid4().hex[:12]}"
            ok, out = _start_container(args.image, workspace, container)
            if not ok:
                record["detail"] = f"container start failed: {out[-500:]}"
                results.append(record)
                print(f"ERROR {tag}: container start failed")
                continue

            output_dir = attempt_dir / "agent"
            try:
                if args.fake_model:
                    _FAKE_STATE["n"] = 0
                request = AgentRunRequest(
                    run_id=tag,
                    role="task",
                    model=model,
                    system_prompt=SYSTEM_PROMPT,
                    task_prompt=_task_prompt(task, root),
                    output_dir=output_dir,
                    container_name=container,
                    container_cwd="/workspace",
                    command_timeout_seconds=args.command_timeout,
                    total_timeout_seconds=args.total_timeout,
                    step_limit=args.step_limit,
                    submission_mode="files",
                    submission_role="task",
                    submission_checker_command=("true",),
                )
                agent_result = backend.run(request)
                record["agent_status"] = agent_result.status
                record["agent_error"] = agent_result.error
                record["agent_tool_calls"] = len(agent_result.tool_calls)
                record["agent_model_calls"] = agent_result.model_calls
                record["agent_tokens"] = {
                    "input": agent_result.input_tokens,
                    "output": agent_result.output_tokens,
                }
                record["agent_session_id"] = agent_result.session_id
            except Exception as exc:  # noqa: BLE001
                record["agent_status"] = "controller-error"
                record["agent_error"] = str(exc)
                print(f"ERROR {tag}: agent controller failed: {exc}")
            finally:
                if not args.keep_containers:
                    _stop_container(container)

            try:
                _diff_workspace(reference, workspace, attempt_dir / "workspace.diff")
            except OSError as exc:
                record["diff_error"] = str(exc)

            judge = _judge(
                image=args.image,
                workspace=workspace,
                task_root=root,
                timeout=args.judge_timeout,
                tag=tag,
            )
            record["judge"] = judge
            report = judge.get("report") or {}
            record["build"] = report.get("build")
            record["tests"] = report.get("tests")
            record["api_removal"] = report.get("api_removal")
            if judge["rc"] == 0 and report.get("status") == "pass":
                record["status"] = "pass"
            elif record["agent_status"] is None:
                record["status"] = "error"
            else:
                record["status"] = "fail"
            record["duration_s"] = round(time.time() - started, 1)
            record["finished_at"] = _now()

            (attempt_dir / "attempt.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            results.append(record)
            print(
                f"{record['status'].upper():5} {tag:<34} agent={record['agent_status']} "
                f"judge_rc={judge['rc']} build={record['build']} tests={record['tests']} "
                f"api={record['api_removal']} {record['duration_s']}s"
            )

    counts: Dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    for record in results:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    summary = {
        "label": args.label,
        "image": args.image,
        "image_id": _image_id(args.image),
        "model": model,
        "context_window": args.context_window,
        "max_output_tokens": args.max_output_tokens,
        "dsh_runtime": identity,
        "tasks": [str(root.relative_to(ROOT)) for root in roots],
        "runs_per_task": args.runs,
        "counts": counts,
        "finished_at": _now(),
    }
    (report_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"SUMMARY pass={counts['pass']} fail={counts['fail']} "
        f"error={counts['error']} skip={counts['skip']}"
    )
    if server is not None and thread is not None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    if counts["error"]:
        return 2
    return 0 if counts["fail"] == 0 and counts["pass"] == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())