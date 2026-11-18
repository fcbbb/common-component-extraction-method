#!/usr/bin/env python3
"""Paired-trial runner for the migration benchmark (both arms).

The same executable drives both arms of the paired comparison:

* ``--arm default`` (condition A) gives the agent the task workspace, the task
  spec, and the ``controlled_bash`` tool, and lets it migrate the code
  directly.  It runs the plain DSH profile ``component-method`` (no
  component-method plugins loaded).
* ``--arm method`` (condition B) gives the *same* task and workspace to one main
  agent with the method plugins loaded (profile
  ``component-method-migration``).  Its fixed system prompt requires the
  component-method workflow first (scan, extract, curate, publish, retrieve,
  materialize ``/workspace/component_bundle``) and then the migration task
  itself, in the same session.  The main agent has no step limit by default and
  a generous safety timeout: component extraction is expensive and must not eat
  the task budget.  ``--method-step-limit`` makes a same-budget comparison
  possible when a run needs it.

The judged artifact is the agent workspace, using the same ``runner.py`` as the
gold positive control.  The only difference between the arms' agent tooling is
that B also has the component-method tools and the fixed workflow prompt.

Execution per scenario:

* ``ipp_to_vsipl``       local Docker image ``migration/ipp:cpu`` with jvsip
                         mounted read-only at ``/opt/vsipl``.
* ``windows_to_kylin``   local Docker image ``migration/kylin:sp3-p2``.
* ``cuda_to_musa``       remote MTT S4000 over SSH.  DSH, the method tools and
                         the judge all run *on the remote host*
                         (``tools/remote_dsh.py``), with the host-shell profile
                         (``component-method-host`` / ``-host-operator``) that
                         exposes stock ``bash``.  The MUSA box has no Docker
                         daemon and no ``CAP_SYS_ADMIN``, so nesting a container
                         there is impossible; instead the attempt has exactly
                         one filesystem, on the machine with the toolchain.
                         Method sub-stages use the host stage plane
                         (``COMPONENT_DSH_STAGE_RUNTIME=host``): they run as
                         child processes of the remote DSH session and write
                         their artifacts into the same attempt tree, so there is
                         nothing to sync back.

Usage::

    # one task per scenario, one run each, real model
    python3 tools/baseline_trial.py \
        --only l2_rubberband_fft --only l2_libuv_thread --only b_l2_layer_norm \
        --runs 1 --label baseline_smoke

    # the other arm: same task, DSH with the component-method plugins loaded
    python3 tools/baseline_trial.py --arm method --only l2_rubberband_fft \
        --runs 1 --label method_smoke

    # plumbing self-test: local fixture model, no credentials, no cost
    python3 tools/baseline_trial.py --arm default --only l2_rubberband_fft --runs 1 \
        --fake-model --label baseline_selftest_ipp

    # prove the judge path by seeding the gold answer instead of an agent
    python3 tools/baseline_trial.py --only l2_rubberband_fft --runs 1 \
        --fake-model --seed-gold --label baseline_judgecheck_ipp

Exit codes: 0 = every judged attempt passed, 1 = at least one attempt failed,
2 = setup error (missing image/credential/remote config), 3 = no tasks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
# The benchmark directory under the repository; the remote checkout mirrors the
# repository, so every remote path to a task or the runner needs this prefix.
BENCH_DIR = ROOT.name
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from shared.harness import taskmodel  # noqa: E402
import agent_trial as at  # noqa: E402
import gold_sanity as gs  # noqa: E402
import remote_setup as rs  # noqa: E402
from remote_dsh import RemoteDshBackend  # noqa: E402
import method_adapter as method_adapter_mod  # noqa: E402

COMPLETION_MARKER = at.COMPLETION_MARKER
AGENT_UID = at.AGENT_UID


def _resource_args() -> List[str]:
    """Keep an unbounded build inside a cgroup instead of killing WSL.

    The WSL VM is small (8 GB here).  Docker-level limits make a runaway
    ``cmake --build -j`` fail inside the container with an OOM-killed compiler,
    while the host and the agent session stay alive.
    """
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

ARM_CONDITIONS = {
    "default": "baseline_direct",
    "method": "component_method",
}
METHOD_MAIN_PROFILE = "component-method-migration"
ARM_DSH_PROFILES = {
    # A stays plain; B is one main agent that also has the method plugins.
    "default": "component-method",
    "method": METHOD_MAIN_PROFILE,
}
# Fixed prompts that define the method condition.  The workflow is the outer
# prompt; the rest are the fixed nested stage prompts.  Hashing all of them
# keeps the experiment identity independent of stdout parsing.
METHOD_PROMPTS = {
    "workflow": ROOT / "config" / "prompts" / "method_workflow_system.txt",
    "extraction_system": (
        ROOT.parent
        / "src"
        / "component_method"
        / "task_execution"
        / "config"
        / "prompts"
        / "extraction"
        / "extract_system.txt"
    ),
    "focus_context_instructions": ROOT.parent / "config" / "prompts" / "focus_context_instructions.txt",
    "protocol_contract_instructions": ROOT.parent / "config" / "prompts" / "protocol_contract_instructions.txt",
    "protocol_contract_schema": ROOT.parent / "config" / "schemas" / "protocol_contract_schema.json",
    "retrieval_system": ROOT.parent / "src" / "component_method" / "retrieval" / "prompts" / "retrieve_system.txt",
    "retrieval_instance": ROOT.parent / "src" / "component_method" / "retrieval" / "prompts" / "retrieve_instance.txt",
}
# The scenario prompts tell the plain agent it has no other tool.  The method
# arm does have the workflow tools, so that one sentence is swapped.
TASK_TOOL_LINE = (
    "Use the controlled_bash tool for every inspection, edit, and build command; "
    "you have no other tool."
)
METHOD_TOOL_LINE = (
    "Use controlled_bash for every inspection, edit, and build command; the "
    "component-method workflow tools described below are also available."
)
# The remote MUSA execution plane runs DSH with the host-shell profile, whose
# shell tool is the stock ``bash`` (no Docker-backed controlled_bash).  The
# fixed prompts are otherwise byte-identical, so the comparison still holds;
# only the tool sentence and the workspace path differ.
HOST_TASK_TOOL_LINE = (
    "Use the bash tool for every inspection, edit, and build command; you have no other tool."
)
HOST_METHOD_TOOL_LINE = (
    "Use bash for every inspection, edit, and build command; the "
    "component-method workflow tools described below are also available."
)
HOST_TOOL_NOTE = (
    "Execution note: on this host the shell tool is named `bash` and takes "
    '{"command": "...", "workdir": "<directory>", "description": "..."}. '
    "Where the text above says `controlled_bash`, use `bash` with `workdir` "
    "instead of `cwd`."
)


def _host_tool_text(text: str) -> str:
    """Rewrite the container-plane shell name and argument for the host plane.

    Both arms compare byte-identical prompts apart from the tool sentence, the
    workspace path and this rename: the host profile has no ``controlled_bash``.
    """
    return (
        text.replace("controlled_bash", "bash")
        .replace('"cwd":', '"workdir":')
        .replace("once with cwd ", "once with workdir ")
    )

IPP_IMAGE_DEFAULT = "migration/ipp:cpu"
KYLIN_IMAGE_DEFAULT = "migration/kylin:sp3-p2"
VSIPL_ROOT_DEFAULT = os.environ.get("VSIPL_ROOT", "")

IPP_ACTIVATION = "export VSIPL_ROOT=/opt/vsipl; export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
KYLIN_ACTIVATION = at.ACTIVATION

IPP_SYSTEM_PROMPT = f"""You are a software engineer migrating a C/C++ component from Intel IPP to VSIPL (jvsip).
Use the controlled_bash tool for every inspection, edit, and build command; you have no other tool.
The task workspace is /workspace and it is the component root. Use /tmp/build as the build directory.
The VSIPL library is installed under $VSIPL_ROOT (include/vsip.h and lib/libvsip.a). External network
access is disabled: every source file you need is already present, and no package can be downloaded.
The Intel IPP implementation you must replace is in /workspace/src; the public header and the public
tests stay as they are. Do not modify tests, build files, or evaluator inputs, and do not special-case
test names to fake behavior. Do not leave any ipps*/ippi* symbol or ipp.h include in the built artifact.
When the implementation is complete and the build command succeeds, call controlled_bash once with
cwd /workspace and a command whose first non-empty output line is exactly {COMPLETION_MARKER}."""

MUSA_SYSTEM_PROMPT = f"""You are a software engineer porting one CUDA/PyTorch operator to Moore Threads MUSA.
Use the controlled_bash tool for every inspection, edit, and build command; you have no other tool.
The task workspace is /workspace and it is the MultiKernelBench snapshot for one operator. Write the
submission file named in the task spec under /workspace/submission/: the spec's ``work/`` prefix
corresponds to /workspace here, so do not create a nested work/ directory. The target is MUSA
SDK 5.2 with mcc on an MTT S4000; use torch_musa and load_inline(..., musa_sources=...). External
network access is disabled: every source file you need is already present. Do not modify the evaluator,
the reference implementation, or the test utilities. Do not special-case shapes or test names.
When the submission is complete and you have checked it as far as the environment allows, call
controlled_bash once with cwd /workspace and a command whose first non-empty output line is exactly
{COMPLETION_MARKER}."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_prompt(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"prompt file is missing: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"prompt file is empty: {path}")
    return text


def _prompt_hashes() -> Dict[str, str]:
    return {
        name: _sha256_file(path)
        for name, path in METHOD_PROMPTS.items()
        if path.is_file()
    }


def _bundle_state(bundle: Path) -> Dict[str, Any]:
    if not bundle.is_dir():
        return {"ok": False, "reason": "missing", "path": str(bundle), "files": 0, "bytes": 0}
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    size = sum(path.stat().st_size for path in files)
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(bundle).as_posix().encode("utf-8") + b"\0")
        digest.update(_sha256_file(path).encode("ascii") + b"\0")
    manifest_path = bundle / "manifest.json"
    component_count = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            component_count = manifest.get("component_count")
        except (OSError, json.JSONDecodeError):
            component_count = None
    return {
        "ok": bool(files),
        "reason": "" if files else "empty",
        "path": str(bundle),
        "files": len(files),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "manifest": str(manifest_path) if manifest_path.is_file() else None,
        "component_count": component_count,
    }


def _tool_call_counts(tool_calls: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count tool calls by name so method and migration work can be seen apart."""
    counts: Dict[str, int] = {}
    for call in tool_calls:
        name = str(call.get("tool") or "unknown")
        counts[name] = counts.get(name, 0) + 1
    return counts


_IMAGE_IDENTITY_CACHE: Dict[str, Dict[str, Any]] = {}


def _image_identity(image: str) -> Dict[str, Any]:
    """Resolve a mutable tag to the immutable image id used by both arms."""
    if not image:
        return {}
    cached = _IMAGE_IDENTITY_CACHE.get(image)
    if cached is not None:
        return dict(cached)
    rc, out = at._run(["docker", "image", "inspect", image], timeout=60)
    if rc != 0:
        identity = {"image": image, "error": out[-500:].strip()}
    else:
        try:
            payload = json.loads(out)
            data = payload[0] if isinstance(payload, list) and payload else {}
            identity = {
                "image": image,
                "id": data.get("Id"),
                "repo_digests": data.get("RepoDigests") or [],
                "created": data.get("Created"),
            }
        except (ValueError, TypeError, IndexError) as exc:
            identity = {"image": image, "error": f"cannot parse docker image inspect: {exc}"}
    _IMAGE_IDENTITY_CACHE[image] = identity
    return dict(identity)


def _image_exists(image: str) -> bool:
    rc, _ = at._run(["docker", "image", "inspect", image], timeout=60)
    return rc == 0


def _read_optional_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _method_stage_usage(task_root: Optional[str]) -> Dict[str, Any]:
    """Aggregate nested-stage usage so B's real cost is not only the outer agent."""
    if not task_root:
        return {}
    root = Path(task_root)
    config = _read_optional_json(root / "config.json")
    task_id = str(config.get("task_id") or root.name)
    extraction_root = root / "runs" / task_id / "extraction_v1"
    summary = _read_optional_json(extraction_root / "summary.json")
    review_summary = _read_optional_json(root / "runs" / task_id / "review_v1" / "summary.json")
    retrieval_attempt = str(config.get("retrieval_attempt") or "retrieval_v1")
    metadata = _read_optional_json(root / "attempts" / retrieval_attempt / "metadata.json")
    usage: Dict[str, Any] = {}
    if summary:
        usage["extraction"] = {
            key: summary.get(key)
            for key in (
                "successful_packets",
                "invalid_packets",
                "failed_packets",
                "component_count",
                "extraction_api_calls",
                "extraction_input_tokens",
                "extraction_output_tokens",
                "extraction_reported_cost_usd",
            )
        }
    if review_summary:
        usage["review"] = {
            "successful_components": review_summary.get("successful_components"),
            "failed_components": review_summary.get("failed_components"),
            "published_components": len(review_summary.get("published_components") or []),
            "withheld_components": len(review_summary.get("withheld_components") or []),
            "max_repair_rounds": review_summary.get("max_repair_rounds"),
            "review_api_calls": review_summary.get("review_api_calls"),
            "review_reported_cost_usd": review_summary.get("review_reported_cost_usd"),
        }
    if metadata:
        usage["retrieval"] = {
            key: metadata.get(key)
            for key in ("model_calls", "input_tokens", "output_tokens", "reported_cost_usd")
        }
    return usage


def _remote_runtime_identity(remote_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Record the MUSA runtime that actually judges/executes, not just an image tag."""
    code = r"""
import json, platform, shutil, subprocess
info = {
    "python": platform.python_version(),
    "platform": platform.platform(),
    "mcc": shutil.which("mcc"),
}
for name in ("torch", "torch_musa"):
    try:
        info[name] = getattr(__import__(name), "__version__", None)
    except Exception as exc:
        info[name] = None
        info[name + "_error"] = f"{type(exc).__name__}: {exc}"
try:
    info["musa_available"] = bool(__import__("torch").musa.is_available())
except Exception as exc:
    info["musa_available"] = None
    info["musa_error"] = f"{type(exc).__name__}: {exc}"
if info.get("mcc"):
    try:
        result = subprocess.run([info["mcc"], "--version"], capture_output=True, text=True, timeout=30)
        info["mcc_version"] = (result.stdout or result.stderr).splitlines()[:1]
    except Exception as exc:
        info["mcc_version_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(info, sort_keys=True))
"""
    rc, out = _ssh_run(remote_cfg, "python3 -c " + shlex.quote(code), timeout=120)
    if rc != 0:
        return {"error": out[-1500:].strip()}
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return {"error": f"cannot parse remote runtime identity: {exc}", "output": out[-1500:]}


def _remote_method_view(
    cfg: Dict[str, Any],
    *,
    remote_repo: str,
    remote_task_root: str,
    remote_output_root: str,
    remote_workspace: str,
    task_id: str,
    run_id: str,
    model: str,
    api_base: str,
    image: str,
) -> Dict[str, Any]:
    """Build the method adapter view on the execution plane.

    The registry it writes contains absolute paths that the method kernel and
    the agent both open, so it has to be produced where they run.  The
    workspace is the synced attempt copy, not the task package's own ``work``
    directory: every stage reads and writes the tree the main agent edits.
    """
    tool = f"{remote_repo}/migration_scenario_validation/tools/method_adapter.py"
    command = (
        f"cd {shlex.quote(remote_repo)} && "
        f"python3 {shlex.quote(tool)} "
        f"--task-root {shlex.quote(remote_task_root)} "
        f"--output-root {shlex.quote(remote_output_root)} "
        f"--workspace {shlex.quote(task_id + '=' + remote_workspace)} "
        f"--run-id {shlex.quote(run_id)} "
        f"--model {shlex.quote(model)} "
        f"--api-base {shlex.quote(api_base)} "
        f"--repository-root {shlex.quote(remote_repo)} "
    )
    if image:
        # The host-shell method runs no containers; the image is only recorded.
        command += f"--runtime-image {shlex.quote('cuda_to_musa=' + image)} "
    rc, out = _ssh_run(cfg, command, timeout=900)
    if rc != 0:
        raise RuntimeError(out[-1200:].strip() or f"remote adapter exited {rc}")
    manifest_path = f"{remote_output_root}/adapter.json"
    rc, out = _ssh_run(cfg, f"cat {shlex.quote(manifest_path)}", timeout=300)
    if rc != 0:
        raise RuntimeError(
            f"cannot read remote adapter manifest {manifest_path}: {out[-800:]}"
        )
    try:
        payload = json.loads(out)
    except ValueError as exc:
        raise RuntimeError(f"cannot parse remote adapter output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("remote adapter returned a non-object")
    return payload


def _start_container(
    image: str,
    workspace: Path,
    name: str,
    *,
    mounts: List[Tuple[Path, str]] = (),
) -> Tuple[bool, str]:
    cmd = [
        "docker", "run", "-d", "--name", name, "--network", "none",
        *_resource_args(),
        "-v", f"{workspace}:/workspace", "-w", "/workspace",
    ]
    for host, container in mounts:
        cmd += ["-v", f"{host}:{container}:ro"]
    cmd += ["--entrypoint", "sleep", image, "infinity"]
    rc, out = at._run(cmd, timeout=300)
    return rc == 0, out.strip()


def _image_present(tag: str) -> bool:
    """Whether the local Docker daemon can start ``tag`` without pulling."""
    if not tag:
        return False
    try:
        rc, _ = at._run(["docker", "image", "inspect", tag], timeout=60)
    except Exception:  # noqa: BLE001
        return False
    return rc == 0


def _make_workspace_root_writable(image: str, workspace: Path) -> Tuple[bool, str]:
    """Let the host-side method stages create ``component_bundle`` on the mount.

    The task workspace is chowned to the agent uid so the sandbox can edit it.
    The preparation stages run on the host and materialize the selected bundle
    inside the same workspace, so the bind-mount root must also be writable by
    the host user.  Children keep their 755/644 modes, so the agent can read the
    bundle but not rewrite it.
    """
    rc, out = at._run(
        [
            "docker", "run", "--rm", "--user", "0",
            "-v", f"{workspace}:/workspace",
            "--entrypoint", "chmod",
            image, "0777", "/workspace",
        ],
        timeout=120,
    )
    return rc == 0, out


def _judge_local(
    image: str,
    workspace: Path,
    task_root: Path,
    *,
    timeout: int,
    tag: str,
    env: Dict[str, str],
    mounts: List[Tuple[Path, str]] = (),
) -> Dict[str, Any]:
    rel = task_root.resolve().relative_to(ROOT).as_posix()
    name = f"baseline-judge-{tag}-{uuid.uuid4().hex[:8]}"
    cmd = [
        "docker", "run", "--rm", "--name", name, "--network", "none",
        *_resource_args(),
        "--user", f"{AGENT_UID}:{AGENT_UID}",
        "-e", "HOME=/tmp", "-e", "PYTHONUNBUFFERED=1",
    ]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += ["-v", f"{ROOT}:/bench:ro", "-v", f"{workspace}:/workspace"]
    for host, container in mounts:
        cmd += ["-v", f"{host}:{container}:ro"]
    cmd += [
        "-w", "/bench", image,
        "python3", "/bench/shared/harness/runner.py",
        "--task-root", f"/bench/{rel}",
        "--work-dir", "/workspace",
        "--build-dir", f"/tmp/judge-build-{tag}",
        "--timeout", str(timeout),
    ]
    started = time.time()
    rc, out = at._run(cmd, timeout=timeout + 300)
    return {
        "rc": rc,
        "duration_s": round(time.time() - started, 1),
        "report": at._extract_json(out),
        "log_tail": out[-6000:],
    }


def _ssh_base(cfg: Dict[str, Any]) -> List[str]:
    cmd = ["ssh"]
    cmd += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        cmd += ["-p", str(cfg["port"])]
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    cmd.append(target)
    return cmd


def _ssh_env(cfg: Dict[str, Any]) -> Dict[str, str]:
    env = dict(os.environ)
    askpass = str(cfg.get("askpass") or "")
    if askpass:
        env["SSH_ASKPASS"] = askpass
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
    return env


_TRANSIENT_SSH = (
    "Connection closed by",
    "Connection reset by",
    "Connection timed out",
    "kex_exchange_identification",
    "ssh_exchange_identification",
    "Broken pipe",
)


def _run_ssh_cmd(cmd: List[str], cfg: Dict[str, Any], *, timeout: int) -> Tuple[int, str]:
    """Run an ssh/rsync command, retrying connection-level failures.

    The rented host intermittently drops a new connection before auth
    ("Connection closed by <ip> port ..."); a reconnect a few seconds later
    works.  Only connection-level errors are retried, never a remote command
    failure.
    """
    last = (255, "")
    for attempt in range(5):
        rc, out = at._run(cmd, timeout=timeout, env=_ssh_env(cfg))
        if rc == 0 or not any(marker in out for marker in _TRANSIENT_SSH):
            return rc, out
        last = (rc, out)
        time.sleep(min(30, 3 * 2**attempt))
    return last


def _ssh_run(cfg: Dict[str, Any], command: str, *, timeout: int = 3600) -> Tuple[int, str]:
    return _run_ssh_cmd(
        _ssh_base(cfg) + [f"bash -lc {shlex.quote(command)}"],
        cfg,
        timeout=timeout,
    )


def _rsync(
    cfg: Dict[str, Any],
    source: Path,
    remote_dir: str,
    *,
    delete: bool = True,
    excludes: Optional[List[str]] = None,
) -> Tuple[int, str]:
    target = (
        f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    )
    ssh_parts = ["ssh"]
    ssh_parts += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        ssh_parts += ["-p", str(cfg["port"])]
    cmd = ["rsync", "-a"]
    if delete:
        cmd.append("--delete")
    for pattern in excludes or []:
        cmd += ["--exclude", pattern]
    cmd += ["-e", " ".join(ssh_parts)]
    cmd += [f"{source}/", f"{target}:{remote_dir}/"]
    rc, out = _run_ssh_cmd(cmd, cfg, timeout=1800)
    return rc, out


def _rsync_from(
    cfg: Dict[str, Any],
    remote_dir: str,
    local_dir: Path,
    *,
    delete: bool = True,
    excludes: Optional[List[str]] = None,
) -> Tuple[int, str]:
    """Pull an attempt workspace back for judging evidence and diffs."""
    target = (
        f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    )
    ssh_parts = ["ssh"]
    ssh_parts += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        ssh_parts += ["-p", str(cfg["port"])]
    cmd = ["rsync", "-a"]
    if delete:
        cmd.append("--delete")
    for pattern in excludes or []:
        cmd += ["--exclude", pattern]
    cmd += ["-e", " ".join(ssh_parts)]
    cmd += [f"{target}:{remote_dir}/", f"{local_dir}/"]
    rc, out = _run_ssh_cmd(cmd, cfg, timeout=1800)
    return rc, out


def _wait_socket(path: Path, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def _start_shim(
    *,
    socket_path: Path,
    transport: str,
    workspace: Path,
    remote_config: Optional[Path],
    remote_root: str,
    agent_user: str,
    isolate_network: bool,
    container_name: str,
) -> subprocess.Popen:
    cmd = [
        sys.executable, str(ROOT / "tools" / "docker_api_shim.py"),
        "--socket", str(socket_path),
        "--transport", transport,
        "--container-name", container_name,
        "--agent-user", agent_user,
    ]
    if transport == "local":
        cmd += ["--root", str(workspace)]
    else:
        cmd += ["--remote-config", str(remote_config), "--remote-root", remote_root]
        # The method stages run here and write into this workspace; the agent
        # writes into the remote copy.  Mirroring around every exec is what
        # makes the component artifacts cross the ssh boundary in both
        # directions.
        cmd += ["--mirror-local", str(workspace)]
        if isolate_network:
            cmd.append("--isolate-network")
    proc = subprocess.Popen(cmd)
    if not _wait_socket(socket_path):
        proc.terminate()
        raise RuntimeError(f"docker API shim did not create {socket_path}")
    return proc


def _seed_gold(task_root: Path, task: Dict[str, Any], workspace: Path) -> List[str]:
    """Copy the reference answer into an attempt workspace (judge self-check)."""
    prov_path = task_root / "provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.is_file() else {}
    staging = workspace.parent / "seed_root"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    (staging / "work").symlink_to(workspace, target_is_directory=True)
    for name in ("gold", "gold_authored"):
        candidate = task_root / name
        if candidate.exists():
            (staging / name).symlink_to(candidate, target_is_directory=True)
    scenario = str(task.get("scenario") or "")
    if scenario == "ipp_to_vsipl":
        error, restored = gs._restore_ipp_gold(staging, task, prov)
    elif scenario == "windows_to_kylin":
        error, restored = gs._restore_kylin_gold(staging)
    else:
        error, restored = gs._restore_musa_gold(staging, task, prov)
    shutil.rmtree(staging, ignore_errors=True)
    if error:
        raise RuntimeError(f"cannot seed gold: {error}")
    return restored


def _task_prompt(task: Dict[str, Any], task_root: Path, scenario: str) -> str:
    spec = str(task.get("spec") or "").strip()
    source = task.get("source") or {}
    lines = [
        f"# {task.get('title') or taskmodel.task_id(task)}",
        "",
        f"Scenario: {scenario}    Level: {task.get('level')}",
        f"Source repository: {source.get('repo', '')} @ {source.get('commit', '')}",
        "",
        spec,
        "",
    ]
    if scenario == "ipp_to_vsipl":
        build = taskmodel.expand_command(
            taskmodel.command_of(task, "build") or "",
            root=Path("/workspace"), work=Path("/workspace"),
            build=Path("/tmp/build"), golden=Path("/workspace"),
        )
        lines += [
            "## Workspace",
            "",
            "The component is at /workspace. The Intel IPP original is in src/, the public",
            "header is in include/, and the public tests are in test/. VSIPL is installed",
            "under $VSIPL_ROOT. Hidden behavior tests and an API-removal gate run after you",
            "finish; they are not visible in the workspace.",
            "",
            "## Build command",
            "",
            "The evaluator runs this exact command from /workspace:",
            "",
            "```bash",
            build,
            "```",
            "",
            f"When the build succeeds, submit with: echo {COMPLETION_MARKER}",
        ]
    elif scenario == "windows_to_kylin":
        return at._task_prompt(task, task_root)
    else:
        op = str(task.get("op_name") or "")
        lines += [
            "## Workspace",
            "",
            "The repository snapshot is at /workspace. The operator contract is in",
            f"reference/; write submission/{op}_submission.py. The evaluator builds a MUSA",
            "torch extension with mcc, runs the reference and your ModelNew on musa:0 with",
            "atol=rtol=1e-4, and rejects CUDA API usage. Hidden tests run after you finish.",
            "",
            f"When the submission is ready, submit with: echo {COMPLETION_MARKER}",
        ]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", action="append", default=[])
    ap.add_argument("--parent", action="append", default=[])
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--level", action="append", default=[])
    ap.add_argument("--arm", choices=sorted(ARM_CONDITIONS), default="default",
                    help="default = plain DSH; method = one main agent with the component "
                         "workflow and the same task")
    ap.add_argument("--dsh-profile", default="",
                    help="override the arm's DSH profile "
                         "(default: component-method for A, component-method-migration for B)")
    ap.add_argument("--method-addendum", default="",
                    help="file with extra system-prompt text for the method "
                         "main agent (appended after the fixed workflow prompt)")
    ap.add_argument("--method-main-timeout", type=int, default=14400,
                    help="wall-clock safety timeout for the method main agent")
    ap.add_argument("--method-step-limit", type=int, default=None,
                    help="optional step limit for the method main agent; default is "
                         "unlimited preparation, matching the documented B budget")
    ap.add_argument("--method-extraction-workers", type=int, default=2,
                    help="concurrent extraction containers inside the workflow")
    ap.add_argument("--method-review-workers", type=int, default=2,
                    help="concurrent component-review containers inside the workflow")
    ap.add_argument("--method-agent-timeout", type=int, default=3600,
                    help="per-component extraction agent timeout inside the workflow")
    ap.add_argument("--method-stage-image", default="",
                    help="local image for the method preparation containers (default: the "
                         "scenario image; remote MUSA needs one that exists locally)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--report-dir", default=None)
    ap.add_argument("--workspace-root", default=None)
    ap.add_argument("--repository-root", default=str(ROOT.parent))
    ap.add_argument("--api-base", default="")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--fake-model", action="store_true")
    ap.add_argument("--seed-gold", action="store_true",
                    help="copy the gold answer instead of waiting for the agent (judge self-check)")
    ap.add_argument("--ipp-image", default=IPP_IMAGE_DEFAULT)
    ap.add_argument("--kylin-image", default=KYLIN_IMAGE_DEFAULT)
    ap.add_argument("--vsipl-root", default=VSIPL_ROOT_DEFAULT)
    ap.add_argument("--remote-config", default="env/remote.yaml")
    ap.add_argument("--remote-dsh-profile", default="",
                    help="DSH profile on the remote MUSA host (default: "
                         "component-method-host for A, component-method-host-operator "
                         "for B; the local --dsh-profile never applies over ssh)")
    ap.add_argument("--musa-transport", choices=["auto", "ssh", "local"], default="auto")
    ap.add_argument("--prepare-timeout", type=int, default=1800)
    ap.add_argument("--command-timeout", type=int, default=600)
    ap.add_argument("--total-timeout", type=int, default=5400)
    ap.add_argument("--step-limit", type=int, default=150)
    ap.add_argument("--context-window", type=int, default=262144)
    ap.add_argument("--max-output-tokens", type=int, default=32768)
    ap.add_argument("--judge-timeout", type=int, default=2400)
    ap.add_argument("--keep-containers", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    arm = args.arm
    condition = ARM_CONDITIONS[arm]
    dsh_profile = args.dsh_profile.strip() or ARM_DSH_PROFILES[arm]
    method_addendum = ""
    method_prompts: Dict[str, str] = {}
    if arm == "method":
        try:
            method_prompts = {
                "workflow": _read_prompt(METHOD_PROMPTS["workflow"]),
            }
        except (OSError, RuntimeError) as exc:
            print(f"ERROR method workflow prompt is unusable: {exc}", file=sys.stderr)
            return 2
        method_addendum = ""
        if args.method_addendum:
            addendum_path = Path(args.method_addendum).expanduser()
            if not addendum_path.is_absolute():
                addendum_path = ROOT / addendum_path
            if not addendum_path.is_file():
                print(f"ERROR --method-addendum is missing: {addendum_path}", file=sys.stderr)
                return 2
            method_addendum = addendum_path.read_text(encoding="utf-8")
        if args.method_main_timeout < 1:
            print("ERROR --method-main-timeout must be positive", file=sys.stderr)
            return 2
        if args.method_step_limit is not None and args.method_step_limit < 1:
            print("ERROR --method-step-limit must be positive when set", file=sys.stderr)
            return 2
        if args.method_extraction_workers < 1 or args.method_review_workers < 1:
            print("ERROR method worker counts must be positive", file=sys.stderr)
            return 2
    elif args.method_addendum:
        print("ERROR --method-addendum is only valid with --arm method", file=sys.stderr)
        return 2
    prompt_hashes = _prompt_hashes() if arm == "method" else {}

    if not args.task_root and not args.parent:
        if args.only:
            # Convenience: a bare task name searches all three scenario slates.
            args.parent = [
                "ipp_vsipl_tasks",
                "windows_to_kylin/tasks",
                "cuda_to_musa/tasks",
            ]
        else:
            ap.error("give --task-root, --parent, or --only")
    roots = at._iter_task_roots(args)
    if not roots:
        print("no task packages found", file=sys.stderr)
        return 3

    # No machine-specific VSIPL default: fail before any prepare/agent work
    # rather than resolving an empty path against the current directory.
    if not str(args.vsipl_root).strip() and any(
        str(taskmodel.load_task(root).get("scenario")) == "ipp_to_vsipl" for root in roots
    ):
        print(
            "ERROR ipp_to_vsipl tasks need --vsipl-root (or VSIPL_ROOT): "
            "a jvsip tree with include/vsip.h and lib/libvsip.a",
            file=sys.stderr,
        )
        return 2

    report_dir = Path(args.report_dir or f"reports/baseline/{args.label}")
    if not report_dir.is_absolute():
        report_dir = ROOT / report_dir
    workspace_root = Path(args.workspace_root or report_dir / "workspaces")
    report_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    # Resolve the MUSA transport once, before any attempt starts.
    remote_cfg: Optional[Dict[str, Any]] = None
    musa_transport = args.musa_transport
    remote_path = Path(args.remote_config)
    if not remote_path.is_absolute():
        remote_path = ROOT / remote_path
    if any(str(taskmodel.load_task(root).get("scenario")) == "cuda_to_musa" for root in roots):
        if musa_transport == "auto":
            musa_transport = "ssh" if remote_path.is_file() else "local"
        if musa_transport == "ssh":
            if not remote_path.is_file():
                print(f"ERROR {remote_path} is missing; copy env/remote.yaml.example "
                      "and fill in the MTT S4000 host, or use --musa-transport local "
                      "for a plumbing check", file=sys.stderr)
                return 2
            remote_cfg = rs._load_config(remote_path)
            # Fail before any task runs if the box cannot execute a MUSA judge.
            checks = [
                "python3 -c 'import yaml, torch, torch_musa; "
                "print(torch.musa.is_available())'",
                "command -v rsync >/dev/null",
            ]
            if remote_cfg.get("isolate_network"):
                checks.append("unshare -n true")
            rc, out = _ssh_run(remote_cfg, " && ".join(checks), timeout=300)
            if rc != 0:
                print(f"ERROR MUSA preflight failed on {remote_cfg.get('host')}:\n"
                      f"{out[-1500:]}", file=sys.stderr)
                return 2
            print(f"musa preflight: available={out.strip().splitlines()[-1] if out.strip() else '?'}")
        else:
            print("NOTE MUSA transport=local: the agent tool path runs on this host "
                  "and the MUSA judge is skipped (no S4000 here).", file=sys.stderr)

    musa_roots = [
        root for root in roots
        if str(taskmodel.load_task(root).get("scenario")) == "cuda_to_musa"
    ]

    creds = at._resolve_credentials(args)
    api_base, api_key, model = creds["api_base"], creds["api_key"], creds["model"]
    server = thread = None
    if args.fake_model:
        server, thread, api_base = at._start_fake_model()
        api_key, model = "fixture-key", "fixture-model"
    elif not (api_base and api_key and model):
        print("ERROR no model credential: set OPENAI_API_BASE / OPENAI_API_KEY / MODEL_NAME, "
              f"fill {creds['repository_root']}/.env, or pass --fake-model", file=sys.stderr)
        return 2

    repo = Path(creds["repository_root"])
    if str(repo / "src") not in sys.path:
        sys.path.insert(0, str(repo / "src"))
    from component_method.agent_runtime.contracts import AgentRunRequest
    from component_method.agent_runtime.dsh_headless import DshHeadlessBackend

    class SocketBackend(DshHeadlessBackend):
        def __init__(
            self,
            docker_socket: str,
            method_environment: Optional[Dict[str, str]] = None,
            **kwargs: Any,
        ) -> None:
            self._docker_socket = docker_socket
            self._method_environment = dict(method_environment or {})
            super().__init__(**kwargs)

        def _minimal_environment(self, request: AgentRunRequest, dsh_home: Path) -> Dict[str, str]:
            env = super()._minimal_environment(request, dsh_home)
            env["COMPONENT_DSH_DOCKER_SOCKET"] = self._docker_socket
            # Stage modules call docker.from_env(); point them at the same
            # socket (the local daemon or the MUSA API shim).
            env["DOCKER_HOST"] = f"unix://{self._docker_socket}"
            for key, value in self._method_environment.items():
                if value:
                    env[key] = value
            return env

    # Remote MUSA: one execution plane.  Ship the repository once, then let
    # DSH, the method tools and the judge all run on the box with the device.
    remote_profile = args.remote_dsh_profile.strip() or (
        "component-method-host" if arm == "default" else "component-method-host-operator"
    )
    remote_probe: Optional[RemoteDshBackend] = None
    remote_identity: Optional[Dict[str, Any]] = None
    if musa_roots and musa_transport == "ssh" and remote_cfg:
        print(f"musa repo sync -> {remote_cfg['remote_root']}/repo")
        rc, out = rs.sync_repo(remote_cfg)
        if rc != 0:
            print(f"ERROR cannot prepare the remote repository:\n{out[-1500:]}",
                  file=sys.stderr)
            if server is not None:
                server.shutdown()
                server.server_close()
            return 2
        try:
            remote_probe = RemoteDshBackend(
                remote_config=remote_cfg,
                api_key=api_key,
                base_url=api_base,
                repository_root=repo,
                profile_name=remote_profile,
                context_window=args.context_window,
                max_output_tokens=args.max_output_tokens,
            )
            remote_identity = remote_probe.validate_runtime()
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR remote DSH runtime is not usable: {exc}", file=sys.stderr)
            if server is not None:
                server.shutdown()
                server.server_close()
            return 2
        print(f"musa dsh={remote_identity.get('dsh_version')} "
              f"node={remote_identity.get('node_version')} profile={remote_profile}")

    try:
        probe = DshHeadlessBackend(
            api_key=api_key,
            base_url=api_base,
            repository_root=repo,
            profile_name=dsh_profile,
            context_window=args.context_window,
            max_output_tokens=args.max_output_tokens,
        )
        probe.validate_runtime()
        identity = probe.runtime_identity()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR DSH runtime is not usable: {exc}", file=sys.stderr)
        if server is not None:
            server.shutdown()
            server.server_close()
        return 2
    if os.environ.get("COMPONENT_DSH_PROFILE"):
        print("WARNING COMPONENT_DSH_PROFILE is set in this shell; this run passes "
              f"profile_name={dsh_profile} explicitly on every request, so the arm wins.",
              file=sys.stderr)
    print(f"dsh={identity.get('dsh_version')} node={identity.get('node_version')} "
          f"model={model} arm={arm} condition={condition} profile={dsh_profile}")
    print(f"api={api_base} tasks={len(roots)} runs={args.runs} musa={musa_transport}")

    results: List[Dict[str, Any]] = []
    for root in roots:
        task = taskmodel.load_task(root)
        task_id = taskmodel.task_id(task)
        scenario = str(task.get("scenario") or "")
        ok, prep_log = at._prepare(root, args.prepare_timeout, False)
        if not ok:
            print(f"ERROR {task_id}: prepare.sh failed", file=sys.stderr)
            results.append({"task": task_id, "status": "error", "detail": "prepare.sh failed"})
            continue
        reference = root / "work"
        if scenario == "ipp_to_vsipl":
            image = args.ipp_image
            if not _image_exists(image):
                print(f"ERROR IPP image {image} is missing; build it with:\n"
                      "  docker build -f env/Dockerfile.ipp -t migration/ipp:cpu .",
                      file=sys.stderr)
                return 2
        elif scenario == "windows_to_kylin":
            image = args.kylin_image
            if not _image_exists(image):
                print(f"ERROR Kylin image {image} is missing", file=sys.stderr)
                return 2
        else:
            image = ""
        task_image = _image_identity(image)
        remote_runtime = (
            _remote_runtime_identity(remote_cfg)
            if scenario == "cuda_to_musa" and musa_transport == "ssh" and remote_cfg
            else None
        )

        for run in range(1, args.runs + 1):
            tag = f"{task_id}-r{run}"
            attempt_dir = report_dir / task_id / f"run{run}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            workspace = workspace_root / tag

            record: Dict[str, Any] = {
                "task": task_id,
                "scenario": scenario,
                "arm": arm,
                "condition": condition,
                "level": task.get("level"),
                "run": run,
                "started_at": _now(),
                "label": args.label,
                "model": model,
                "dsh_profile": dsh_profile,
                "method_profile": dsh_profile if arm == "method" else None,
                "method_budget": (
                    {
                        "step_limit": args.method_step_limit,
                        "total_timeout": args.method_main_timeout,
                        "command_timeout": args.command_timeout,
                        "extraction_workers": args.method_extraction_workers,
                        "review_workers": args.method_review_workers,
                        "agent_timeout": args.method_agent_timeout,
                    }
                    if arm == "method"
                    else None
                ),
                "method_prompt_hashes": prompt_hashes if arm == "method" else None,
                "component_bundle": None,
                "task_image": task_image or None,
                "remote_runtime": remote_runtime,
                "dsh_runtime": (
                    remote_identity
                    if scenario == "cuda_to_musa" and musa_transport == "ssh" and remote_identity
                    else identity
                ),
                "remote_dsh_profile": (
                    remote_profile
                    if scenario == "cuda_to_musa" and musa_transport == "ssh"
                    else None
                ),
                "transport": musa_transport if scenario == "cuda_to_musa" else "docker",
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
            if scenario == "cuda_to_musa":
                if workspace.exists():
                    shutil.rmtree(workspace, ignore_errors=True)
                shutil.copytree(reference, workspace, symlinks=True)
            else:
                try:
                    at._copy_workspace(reference, workspace, image)
                except OSError as exc:
                    record["detail"] = f"cannot copy workspace: {exc}"
                    results.append(record)
                    print(f"ERROR {tag}: cannot copy workspace: {exc}")
                    continue
                # chown happens after optional gold seeding: the host user
                # cannot write into a workspace owned by uid 10001.
                chown_image = image

            if args.seed_gold:
                try:
                    record["gold_seeded"] = _seed_gold(root, task, workspace)
                except Exception as exc:  # noqa: BLE001
                    record["detail"] = f"gold seeding failed: {exc}"
                    results.append(record)
                    print(f"ERROR {tag}: {record['detail']}")
                    continue

            if scenario != "cuda_to_musa":
                ok, out = at._chown(chown_image, workspace)
                if not ok:
                    record["detail"] = f"chown failed: {out[-500:]}"
                    results.append(record)
                    print(f"ERROR {tag}: chown failed")
                    continue
                if arm == "method":
                    ok, out = _make_workspace_root_writable(chown_image, workspace)
                    if not ok:
                        record["detail"] = f"workspace mode failed: {out[-500:]}"
                        results.append(record)
                        print(f"ERROR {tag}: workspace mode failed")
                        continue

            sandbox_name = f"baseline-{uuid.uuid4().hex[:12]}"
            shim_proc: Optional[subprocess.Popen] = None
            socket_path: Optional[Path] = None
            remote_ws = ""
            if scenario == "cuda_to_musa":
                remote_base = f"{remote_cfg['remote_root']}/runs/{args.label}/{tag}" if remote_cfg else ""
                remote_ws = f"{remote_base}/workspace"
                if musa_transport == "ssh" and remote_cfg:
                    rc, out = _ssh_run(remote_cfg, f"mkdir -p {shlex.quote(remote_base)}")
                    if rc != 0:
                        record["detail"] = f"remote mkdir failed: {out[-800:]}"
                        results.append(record)
                        print(f"ERROR {tag}: remote mkdir failed")
                        continue
                    # One copy of the workspace, on the box that executes the
                    # agent and the judge.  Nothing is mirrored afterwards.
                    rc, out = _rsync(remote_cfg, workspace, remote_ws)
                    if rc != 0:
                        record["detail"] = f"workspace sync failed: {out[-800:]}"
                        results.append(record)
                        print(f"ERROR {tag}: workspace sync failed: {out[-800:]}")
                        continue
                    agent_user = str(remote_cfg.get("agent_user") or "")
                    if agent_user:
                        rc, out = _ssh_run(
                            remote_cfg,
                            f"chown -R {agent_user}:{agent_user} {shlex.quote(remote_ws)}",
                        )
                        if rc != 0:
                            record["detail"] = f"cannot chown workspace to {agent_user}: {out[-500:]}"
                            results.append(record)
                            print(f"ERROR {tag}: {record['detail']}")
                            continue
                    # Without agent_user the agent runs as the ssh user, which
                    # already owns the synced workspace; no chown is needed.
                elif musa_transport == "local":
                    remote_ws = str(workspace.resolve())
                    socket_path = Path(f"/tmp/dsh-shim-{uuid.uuid4().hex[:12]}.sock")
                    try:
                        shim_proc = _start_shim(
                            socket_path=socket_path,
                            transport="local",
                            workspace=workspace,
                            remote_config=None,
                            remote_root=remote_ws,
                            agent_user="",
                            isolate_network=False,
                            container_name=sandbox_name,
                        )
                    except Exception as exc:  # noqa: BLE001
                        record["detail"] = f"shim start failed: {exc}"
                        results.append(record)
                        print(f"ERROR {tag}: {record['detail']}")
                        continue
                    docker_socket = str(socket_path)
            else:
                mounts = [(Path(args.vsipl_root).resolve(), "/opt/vsipl")] if scenario == "ipp_to_vsipl" else []
                ok, out = _start_container(image, workspace, sandbox_name, mounts=mounts)
                if not ok:
                    record["detail"] = f"container start failed: {out[-500:]}"
                    results.append(record)
                    print(f"ERROR {tag}: container start failed")
                    continue
                docker_socket = "/var/run/docker.sock"

            remote_host = (
                scenario == "cuda_to_musa"
                and musa_transport == "ssh"
                and remote_cfg is not None
            )
            activation = (
                ""
                if remote_host
                else (IPP_ACTIVATION if scenario == "ipp_to_vsipl" else KYLIN_ACTIVATION)
            )
            task_tool_line = HOST_TASK_TOOL_LINE if remote_host else TASK_TOOL_LINE
            method_tool_line = HOST_METHOD_TOOL_LINE if remote_host else METHOD_TOOL_LINE
            base_system_prompt = {
                "ipp_to_vsipl": IPP_SYSTEM_PROMPT,
                "windows_to_kylin": at.SYSTEM_PROMPT,
                "cuda_to_musa": MUSA_SYSTEM_PROMPT,
            }[scenario]
            if remote_host:
                # The remote workspace is not at /workspace (the image already
                # owns that directory); name the real path instead.  The host
                # profile's shell is `bash`, not the Docker-backed
                # `controlled_bash`, so rename it in both arms.
                base_system_prompt = _host_tool_text(
                    base_system_prompt.replace("/workspace", remote_ws)
                )
            system_prompt = base_system_prompt

            # Method arm: one main agent needs a registered run/task.  The
            # adapter is rebuilt per attempt because every attempt gets its own
            # workspace and therefore its own trusted repository path.
            method_view: Optional[Dict[str, Any]] = None
            method_adapter_note = ""
            method_system_prompt = ""
            if arm == "method":
                if remote_host:
                    # Adapt on the execution plane so every path in the
                    # registry points at files that exist there.
                    remote_task_root = (
                        f"{remote_cfg['remote_root']}/repo/{BENCH_DIR}/"
                        f"{root.resolve().relative_to(ROOT).as_posix()}"
                    )
                    try:
                        method_view = _remote_method_view(
                            remote_cfg,
                            remote_repo=f"{remote_cfg['remote_root']}/repo",
                            remote_task_root=remote_task_root,
                            remote_output_root=f"{remote_base}/method",
                            remote_workspace=remote_ws,
                            task_id=task_id,
                            run_id=tag,
                            model=model,
                            api_base=api_base,
                            image=image,
                        )
                        method_adapter_note = "active (remote)"
                    except Exception as exc:  # noqa: BLE001
                        method_adapter_note = f"failed: {exc}"
                        print(f"ERROR {tag}: remote method adapter failed: {exc}",
                              file=sys.stderr)
                else:
                    # Local scenarios: the stages run in this host's DSH; they
                    # need a local image for their sandbox.
                    stage_image = (
                        args.method_stage_image
                        or os.environ.get("METHOD_STAGE_IMAGE")
                        or image
                    )
                    record["method_stage_image"] = stage_image
                    if not _image_present(stage_image):
                        method_adapter_note = (
                            "failed: method preparation stages run on the benchmark host "
                            f"and need a local image, but {stage_image!r} is not present. "
                            "Set --method-stage-image or METHOD_STAGE_IMAGE (any image with "
                            "bash and python3)."
                        )
                        print(f"ERROR {tag}: method adapter {method_adapter_note}",
                              file=sys.stderr)
                    else:
                        try:
                            method_view = method_adapter_mod.build_workspace(
                                [root],
                                output_root=attempt_dir / "method",
                                run_id=tag,
                                model=model,
                                api_base=api_base,
                                runtime_images={scenario: stage_image},
                                repository_root=repo,
                                workspaces={task_id: workspace},
                                extraction_workers=args.method_extraction_workers,
                                review_workers=args.method_review_workers,
                                agent_timeout=args.method_agent_timeout,
                            )
                            method_adapter_note = "active"
                        except Exception as exc:  # noqa: BLE001
                            method_adapter_note = f"failed: {exc}"
                            print(f"ERROR {tag}: method adapter failed: {exc}",
                                  file=sys.stderr)
                if method_view is not None:
                    registration = (
                        "\n\nRegistered identity for this session: "
                        f"run_id={method_view['run_id']!r}, task_id={task_id!r}. "
                        "Pass exactly these values to every method tool."
                    )
                    workflow_prompt = method_prompts["workflow"]
                    if remote_host:
                        workflow_prompt = _host_tool_text(
                            workflow_prompt.replace("/workspace", remote_ws)
                        )
                    method_system_prompt = (
                        base_system_prompt.replace(task_tool_line, method_tool_line)
                        .rstrip()
                        + "\n\n"
                        + workflow_prompt.rstrip()
                    )
                    if method_addendum.strip():
                        method_system_prompt += "\n\n" + method_addendum.strip()
                    if remote_host:
                        method_system_prompt += "\n\n" + HOST_TOOL_NOTE
                    method_system_prompt += registration
            record["method_adapter"] = method_adapter_note or None
            if method_view is not None:
                record["method_task_root"] = method_view["tasks"][task_id]["task_root"]
                record["method_prompt_sha256"] = hashlib.sha256(
                    method_system_prompt.encode("utf-8")
                ).hexdigest()
            if arm == "method" and method_view is None:
                # Do not let an unadapted attempt masquerade as the B condition.
                # Remote MUSA is adapted the same way as the local scenarios:
                # the stages run here and the shim mirrors their output into
                # the remote workspace.
                record["status"] = "error"
                record["detail"] = (
                    f"method workflow is unavailable: "
                    f"{method_adapter_note or 'no adapter view'}"
                )
                if not args.keep_containers and scenario != "cuda_to_musa":
                    at._stop_container(sandbox_name)
                if shim_proc is not None:
                    shim_proc.send_signal(signal.SIGTERM)
                    try:
                        shim_proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        shim_proc.kill()
                results.append(record)
                continue
            output_dir = attempt_dir / "agent"
            bundle = workspace / "component_bundle"
            workflow_ok = arm != "method"
            try:
                method_environment: Optional[Dict[str, str]] = None
                if arm == "method":
                    entry = method_view["tasks"][task_id]
                    method_environment = {
                        "COMPONENT_DSH_COMPONENT_LIBRARY": entry["library"],
                        "COMPONENT_DSH_SELECTION_PATH": entry["selection_path"],
                        "COMPONENT_DSH_COVERAGE_PATH": entry["coverage_path"],
                        "COMPONENT_DSH_BUNDLE_DESTINATION": entry["bundle_destination"],
                        # The nested stage agents build their own model route;
                        # without this the extraction runner falls back to its
                        # 16k default and a long reasoning turn ends on
                        # `max-tokens` before the agent writes its submission.
                        # Use the same budget as the outer workflow agent.
                        "COMPONENT_DSH_MAX_OUTPUT_TOKENS": str(args.max_output_tokens),
                    }
                    if remote_host:
                        # The box has no Docker daemon; the nested stage agents
                        # run in the same filesystem as this session.
                        method_environment["COMPONENT_DSH_STAGE_RUNTIME"] = "host"
                if args.fake_model:
                    at._FAKE_STATE["n"] = 0
                if remote_host:
                    assert remote_probe is not None
                    backend = remote_probe
                else:
                    backend = SocketBackend(
                        docker_socket=docker_socket,
                        method_environment=method_environment,
                        api_key=api_key,
                        base_url=api_base,
                        repository_root=repo,
                        profile_name=dsh_profile,
                        runtime_activation=activation if scenario != "cuda_to_musa" else "",
                        context_window=args.context_window,
                        max_output_tokens=args.max_output_tokens,
                        host_environment=(
                            {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
                            if args.fake_model
                            else None
                        ),
                    )
                task_prompt = _task_prompt(task, root, scenario)
                if remote_host:
                    task_prompt = task_prompt.replace("/workspace", remote_ws)
                request = AgentRunRequest(
                    run_id=tag,
                    role="task",
                    model=model,
                    system_prompt=(
                        method_system_prompt if arm == "method" else system_prompt
                    ),
                    task_prompt=task_prompt,
                    profile_name=remote_profile if remote_host else dsh_profile,
                    output_dir=output_dir,
                    container_name=sandbox_name,
                    container_cwd=remote_ws if remote_host else "/workspace",
                    command_timeout_seconds=args.command_timeout,
                    total_timeout_seconds=(
                        args.method_main_timeout if arm == "method" else args.total_timeout
                    ),
                    # The method main agent does preparation and the task in one
                    # session.  Its step limit is optional (default: unlimited
                    # preparation); an explicit --method-step-limit makes a
                    # same-budget comparison possible.
                    step_limit=(
                        args.method_step_limit if arm == "method" else args.step_limit
                    ),
                    # The host-shell profile exposes stock bash, not the
                    # Docker-backed controlled_bash that writes the validated
                    # submission record, so there is nothing to validate there.
                    submission_mode="none" if remote_host else "files",
                    submission_role="task",
                    submission_checker_command=("true",),
                    repository=workspace if arm == "method" else None,
                    method_registry=(
                        Path(method_view["registry"]) if arm == "method" else None
                    ),
                    method_task_id=task_id if arm == "method" else None,
                    method_offline_tasks=(
                        Path(method_view["offline_tasks"]) if arm == "method" else None
                    ),
                )
                if remote_host:
                    agent_result = backend.run(
                        request,
                        remote_output_dir=f"{remote_base}/agent",
                        path_map=[
                            (workspace, remote_ws),
                            (attempt_dir, remote_base),
                        ],
                        method_environment=method_environment,
                    )
                    # The method kernel writes its stage artefacts on the
                    # remote host; pull them so the usage scan and the evidence
                    # see the same bytes the agent saw.
                    if arm == "method":
                        pull_rc, pull_out = _rsync_from(
                            remote_cfg, f"{remote_base}/method", attempt_dir / "method"
                        )
                        if pull_rc != 0:
                            record["method_pull_error"] = pull_out[-800:]
                        else:
                            record["method_task_root"] = str(
                                attempt_dir / "method" / "tasks" / task_id
                            )
                else:
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
                if remote_host:
                    # The agent wrote to the remote workspace; bring it back
                    # before anything here inspects it.  The judge still runs
                    # remotely, so a failed pull costs evidence, not the verdict.
                    if agent_user:
                        _ssh_run(
                            remote_cfg,
                            f"chmod -R a+rX {shlex.quote(remote_ws)}",
                            timeout=300,
                        )
                    pull_rc, pull_out = _rsync_from(remote_cfg, remote_ws, workspace)
                    record["workspace_pull_rc"] = pull_rc
                    if pull_rc != 0:
                        record["pull_error"] = pull_out[-800:]
                if arm == "method":
                    record["method_tool_calls"] = _tool_call_counts(agent_result.tool_calls)
                    record["method_stage_usage"] = _method_stage_usage(
                        record.get("method_task_root")
                    )
                    bundle_state = _bundle_state(bundle)
                    record["component_bundle"] = bundle_state
                    workflow_ok = bool(
                        bundle_state["ok"]
                        and (
                            bundle_state.get("component_count") is None
                            or int(bundle_state["component_count"]) > 0
                        )
                    )
                    if not workflow_ok:
                        record["agent_error"] = (
                            f"method workflow produced no usable bundle at {bundle} "
                            f"({bundle_state.get('reason') or 'empty'}); "
                            f"agent_status={agent_result.status}"
                        )
            except Exception as exc:  # noqa: BLE001
                record["agent_status"] = "controller-error"
                record["agent_error"] = str(exc)
                print(f"ERROR {tag}: agent controller failed: {exc}")
            finally:
                if not args.keep_containers and scenario != "cuda_to_musa":
                    at._stop_container(sandbox_name)
                if shim_proc is not None:
                    shim_proc.send_signal(signal.SIGTERM)
                    try:
                        shim_proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        shim_proc.kill()

            if not workflow_ok:
                record["status"] = "error"
                record["detail"] = (
                    record.get("agent_error") or "method workflow produced no component bundle"
                )
                record["duration_s"] = round(time.time() - started, 1)
                record["finished_at"] = _now()
                (attempt_dir / "attempt.json").write_text(
                    json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                results.append(record)
                print(
                    f"{record['status'].upper():5} {tag:<34} "
                    f"bundle=missing {record['duration_s']}s"
                )
                continue

            try:
                at._diff_workspace(reference, workspace, attempt_dir / "workspace.diff")
            except OSError as exc:
                record["diff_error"] = str(exc)

            if scenario == "cuda_to_musa" and musa_transport == "local":
                record["judge"] = {
                    "rc": None,
                    "duration_s": 0,
                    "report": None,
                    "log_tail": "",
                    "skipped": "no MUSA device on this host (transport=local)",
                }
                record["status"] = "skip"
                record["detail"] = "agent path exercised; MUSA judge skipped"
            else:
                judge_started = time.time()
                if scenario == "ipp_to_vsipl":
                    judge = _judge_local(
                        image, workspace, root,
                        timeout=args.judge_timeout, tag=tag,
                        env={"VSIPL_ROOT": "/opt/vsipl"},
                        mounts=[(Path(args.vsipl_root).resolve(), "/opt/vsipl")],
                    )
                elif scenario == "windows_to_kylin":
                    judge = at._judge(
                        image=image, workspace=workspace, task_root=root,
                        timeout=args.judge_timeout, tag=tag,
                    )
                else:
                    assert remote_cfg is not None
                    remote_repo = f"{remote_cfg['remote_root']}/repo"
                    remote_bench = f"{remote_repo}/{BENCH_DIR}"
                    rel = root.resolve().relative_to(ROOT).as_posix()
                    command = (
                        f"cd {shlex.quote(remote_bench)} && python3 shared/harness/runner.py "
                        f"--task-root {shlex.quote(remote_bench + '/' + rel)} "
                        f"--work-dir {shlex.quote(remote_ws)} "
                        f"--build-dir {shlex.quote('/tmp/judge-build-' + tag)} "
                        f"--timeout {args.judge_timeout}"
                    )
                    rc, out = _ssh_run(remote_cfg, command, timeout=args.judge_timeout + 600)
                    judge = {
                        "rc": rc,
                        "duration_s": round(time.time() - judge_started, 1),
                        "report": at._extract_json(out),
                        "log_tail": out[-6000:],
                    }
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
            bundle_note = (
                f"components={(record.get('component_bundle') or {}).get('component_count')} "
                f"method_calls={sum((record.get('method_tool_calls') or {}).values())} "
                if arm == "method"
                else ""
            )
            print(
                f"{record['status'].upper():5} {tag:<34} {bundle_note}"
                f"agent={record['agent_status']} "
                f"build={record.get('build')} tests={record.get('tests')} "
                f"api={record.get('api_removal')} {record['duration_s']}s"
            )

    # Setup failures take an early ``continue`` above and never reach the
    # per-attempt write; persist them here so attempt.json carries the reason
    # instead of only the summary count.
    for record in results:
        attempt_path = (
            report_dir / str(record["task"]) / f"run{record['run']}" / "attempt.json"
        )
        if not attempt_path.is_file():
            attempt_path.parent.mkdir(parents=True, exist_ok=True)
            attempt_path.write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    counts: Dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    for record in results:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    summary = {
        "label": args.label,
        "arm": arm,
        "condition": condition,
        "model": model,
        "context_window": args.context_window,
        "max_output_tokens": args.max_output_tokens,
        "dsh_profile": dsh_profile,
        "method_profile": dsh_profile if arm == "method" else None,
        "method_budget": (
            {
                "step_limit": args.method_step_limit,
                "total_timeout": args.method_main_timeout,
                "command_timeout": args.command_timeout,
                "extraction_workers": args.method_extraction_workers,
                "review_workers": args.method_review_workers,
                "agent_timeout": args.method_agent_timeout,
            }
            if arm == "method"
            else None
        ),
        "method_prompt_hashes": prompt_hashes if arm == "method" else None,
        "task_images": {
            record["scenario"]: record.get("task_image")
            for record in results
            if record.get("task_image")
        },
        "remote_runtimes": {
            record["scenario"]: record.get("remote_runtime")
            for record in results
            if record.get("remote_runtime")
        },
        "dsh_runtime": identity,
        "tasks": [str(root.relative_to(ROOT)) for root in roots],
        "runs_per_task": args.runs,
        "musa_transport": musa_transport,
        "counts": counts,
        "finished_at": _now(),
    }
    (report_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"SUMMARY pass={counts['pass']} fail={counts['fail']} "
          f"error={counts['error']} skip={counts['skip']}")
    if server is not None and thread is not None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    if counts["error"]:
        return 2
    if counts["fail"]:
        return 1
    # A skip is an explicitly requested non-judged path (dry-run or MUSA
    # transport=local), so it does not make the run fail.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())