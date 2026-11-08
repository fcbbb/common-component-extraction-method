"""Run the final coding task through DSH against one official task container."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
import time
from types import SimpleNamespace
from typing import Any

import docker

from component_method.agent_runtime import (
    AgentRunRequest,
    BackendSettings,
    create_agent_backend,
    selected_backend_name,
)
from component_method.agent_runtime.status import AGENT_PROCESS_ERROR, SUBMITTED
from component_method.library_publish.agent_bundle import agent_bundle_prompt
from component_method.languages.task_environment import bundle_environment
from component_method.languages.python.task_runtime import DIRECT_PYTHONPATH, COMPONENT_PYTHONPATH

from component_usage import collect_component_usage


COMPLETION_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
TOOL_ENV = {
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PAGER": "cat",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PIP_NO_INDEX": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "TMPDIR": "/tmp",
}


def model_env() -> dict[str, str]:
    from common import model_env as load_model_env

    return load_model_env()


def settings() -> dict:
    from common import settings as load_settings

    return load_settings()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def initialize_task(container: Any, official: dict) -> None:
    from environment import initialize_task as initialize

    initialize(container, official)


def network_probe(container: Any) -> dict:
    from environment import network_probe as probe

    return probe(container)


def collect_patch(environment: Any, base_commit: str, *, allow_empty: bool = False) -> str:
    from environment import collect_patch as capture

    return capture(environment, base_commit, allow_empty=allow_empty)


def check_patch(image: str, patch: str) -> None:
    from environment import check_patch as check

    check(image, patch)


def task_config_directory() -> Path:
    from common import CONFIG

    return CONFIG


PATCH_CHECKER = r"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

base_commit = sys.argv[1]
subprocess.run(["git", "add", "-A"], check=True)
patch = subprocess.check_output([
    "git", "-c", "core.pager=cat", "diff", "--cached", "--binary",
    "--no-ext-diff", "--unified=3", base_commit,
])
if not patch.lstrip().startswith(b"diff --git "):
    print("Submission rejected: the task worktree has no complete Git patch.")
    raise SystemExit(1)
handle, index_path = tempfile.mkstemp(prefix="component-task-index-", dir="/tmp")
os.close(handle)
Path(index_path).unlink()
environment = os.environ.copy()
environment["GIT_INDEX_FILE"] = index_path
try:
    subprocess.run(["git", "read-tree", base_commit], check=True, env=environment)
    checked = subprocess.run(
        ["git", "apply", "--cached", "--check", "--whitespace=nowarn", "-"],
        input=patch,
        env=environment,
    )
    if checked.returncode:
        print("Submission rejected: patch does not apply to the clean task baseline.")
        raise SystemExit(1)
finally:
    try:
        Path(index_path).unlink()
    except FileNotFoundError:
        pass
print("Task patch captured from the worktree and checked against the clean baseline.")
""".strip()


DSH_TASK_SYSTEM_PROMPT = f"""You are a software engineer solving one task in an isolated repository.
Use the controlled_bash tool for every repository inspection, edit, and validation command.
The repository is /testbed and external network access is disabled.
Modify only production source files needed by the task. Do not modify tests or project configuration.
Inspect the existing code before editing and run focused local validation after the change.
When the implementation is complete, call controlled_bash once with cwd /testbed and a command
whose first non-empty output line is exactly {COMPLETION_MARKER}.
The controller captures the patch from the real Git worktree and validates it; do not put a patch in
the final answer and do not claim completion without using that command."""


def patch_checker_command(base_commit: str) -> tuple[str, ...]:
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise ValueError("base_commit must be a full lowercase Git SHA")
    return ("python", "-c", PATCH_CHECKER, base_commit)


def task_prompt(problem_statement: str, *, components: bool, bundle: Path | None = None) -> str:
    prompt = f"""<pr_description>
{problem_statement}
</pr_description>

Implement the requested behavior in /testbed. Preserve behavior outside the request. Dependencies
are already installed, so do not download packages or access the network. Use focused scripts under
/tmp when repository tests are unsuitable."""
    if components:
        manifest_path = bundle / "manifest.json" if bundle else None
        artifact_bundle = manifest_path and manifest_path.is_file() and read(manifest_path).get("schema_version") == 8
        component_text = (agent_bundle_prompt(task_config_directory(), bundle=bundle) if artifact_bundle
                          else agent_bundle_prompt(task_config_directory()))
        component_text = component_text.replace(
            "In your final task-submission response, if you used a delivered component, include "
            '`{"component_usage": ["component identifier / entrypoint"]}` on a separate line '
            "outside the Bash block; otherwise omit it. Keep the existing final submission command "
            "in that same response, without an extra turn.",
            "If you use a delivered component, write a JSON object with exactly the field "
            '`{"component_usage": ["component identifier / entrypoint"]}` to '
            "/tmp/component_usage.json before submitting. Omit the file when no component is used.",
        )
        prompt += "\n\n" + component_text.strip()
    return prompt + "\n"


class DshTaskEnvironment:
    """Expose the small execute contract used by the existing patch collector."""

    def __init__(self, container: Any, image: str, pythonpath: str, language_environment=None) -> None:
        self.container = container
        self.config = SimpleNamespace(image=image)
        self.pythonpath = pythonpath
        self.language_environment = language_environment or {}

    def ensure_running(self) -> None:
        self.container.reload()
        if self.container.status != "running":
            raise RuntimeError("TaskEnvironmentLost: task container is not running")

    def execute(self, command: str, cwd: str = "", *, timeout: int | None = None) -> dict:
        self.ensure_running()
        seconds = int(timeout or 60)
        wrapped = f"timeout --signal=TERM --kill-after=5s {seconds}s /bin/bash -lc {shlex.quote(command)}"
        result = self.container.exec_run(
            ["/bin/bash", "-lc", wrapped],
            workdir=cwd or "/testbed",
            environment={**TOOL_ENV, "PYTHONPATH": self.pythonpath, **self.language_environment},
            user="10001:10001",
            demux=False,
            tty=False,
            privileged=False,
        )
        output = result.output or b""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {"output": output, "returncode": result.exit_code, "exception_info": ""}


def _container_name(task_id: str, arm: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"component-task-{arm}-{task_id}").strip("-.")
    suffix = hashlib.sha256(f"{os.getpid()}-{time.time_ns()}".encode()).hexdigest()[:10]
    return f"{safe[:48]}-{suffix}"


def _create_container(client: Any, *, image: str, name: str, bundle: Path | None) -> Any:
    volumes = {}
    if bundle is not None:
        volumes[str(bundle.resolve())] = {
            "bind": "/testbed/component_bundle",
            "mode": "ro",
        }
    return client.containers.create(
        image=image,
        entrypoint=[],
        name=name,
        command=["sleep", "infinity"],
        working_dir="/testbed",
        volumes=volumes,
        environment={
            "PIP_NO_INDEX": "1",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
        },
        network_mode="none",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        pids_limit=128,
        labels={"component-method.role": "final-task"},
    )


def _explicit_component_usage(container: Any) -> list[str]:
    script = (
        "import json,pathlib; p=pathlib.Path('/tmp/component_usage.json'); "
        "print(p.read_text() if p.is_file() else '{}')"
    )
    try:
        result = container.exec_run(
            ["python", "-c", script],
            user="10001:10001",
            environment=TOOL_ENV,
        )
    except Exception:
        return []
    if result.exit_code:
        return []
    output = result.output or b""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    try:
        value = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict) or set(value) != {"component_usage"}:
        return []
    entries = value["component_usage"]
    if not isinstance(entries, list):
        return []
    usage = []
    for entry in entries:
        if isinstance(entry, str) and entry.strip() and entry.strip() not in usage:
            usage.append(entry.strip())
    return usage


def _merged_usage(messages: list[dict], explicit: list[str]) -> list[str]:
    usage = collect_component_usage(messages)
    for entry in explicit:
        if entry not in usage:
            usage.append(entry)
    return usage


def run_dsh_task(
    *,
    task_id: str,
    arm: str,
    image: str,
    bundle: Path | None,
    official: dict,
    problem_statement: str,
    out: Path,
    client: Any | None = None,
    backend: Any | None = None,
) -> dict:
    """Run one bounded DSH task attempt and return the stable result payload."""
    environment_values = model_env()
    pythonpath = COMPONENT_PYTHONPATH if bundle is not None else DIRECT_PYTHONPATH
    language_environment = bundle_environment(bundle)
    runtime_activation = (
        "; ".join(f"export {key}={shlex.quote(value)}" for key, value in language_environment.items())
        + "; export PIP_NO_INDEX=1; "
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy"
    )
    backend = backend or create_agent_backend(
        BackendSettings(
            api_key=environment_values["OPENAI_API_KEY"],
            base_url=environment_values["OPENAI_API_BASE"],
            runtime_activation=runtime_activation,
        )
    )
    backend_name = str(
        backend.runtime_identity().get("backend") or selected_backend_name()
    )
    client = client or docker.from_env()
    container = _create_container(
        client,
        image=image,
        name=_container_name(task_id, arm),
        bundle=bundle,
    )
    started_at = now()
    started_clock = time.monotonic()
    proof: dict[str, Any] | None = None
    backend_result = None
    patch = ""
    status = AGENT_PROCESS_ERROR
    error: str | None = None
    extra: dict[str, Any] = {}
    runtime_identity = backend.runtime_identity()
    try:
        container.start()
        initialize_task(container, official)
        proof = network_probe(container)
        proof.update(container_id=container.id, container_name=container.name)
        write(out / "network_proof.json", proof)
        environment = DshTaskEnvironment(container, image, pythonpath, language_environment)
        backend_result = backend.run(
            AgentRunRequest(
                run_id=f"{arm}-{task_id}",
                role="task",
                model=environment_values["MODEL_NAME"],
                system_prompt=DSH_TASK_SYSTEM_PROMPT,
                task_prompt=task_prompt(problem_statement, components=bundle is not None, bundle=bundle),
                output_dir=out,
                container_name=container.name,
                container_cwd="/testbed",
                command_timeout_seconds=60,
                total_timeout_seconds=settings()["task_timeout_seconds"],
                step_limit=settings()["step_limit"],
                submission_mode="patch",
                submission_role="task",
                submission_checker_command=patch_checker_command(official["base_commit"]),
            )
        )
        status = backend_result.status
        error = backend_result.error
        try:
            patch = collect_patch(
                environment,
                official["base_commit"],
                allow_empty=status != SUBMITTED,
            )
            if patch:
                check_patch(image, patch)
        except Exception as exc:
            extra["patch_capture_error"] = str(exc)
            if status == SUBMITTED:
                status = AGENT_PROCESS_ERROR
                error = f"submitted task patch failed controller validation: {exc}"
                patch = ""
        if status == SUBMITTED and not patch:
            status = AGENT_PROCESS_ERROR
            error = "DSH reported submission without a non-empty validated worktree patch"
        if patch:
            target = out / ("submitted.patch" if status == SUBMITTED else "diagnostic.patch")
            target.write_text(patch, encoding="utf-8")
            write(
                out / "patch_capture.json",
                {
                    "source": "actual_repository_diff",
                    "base_commit": official["base_commit"],
                    "sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "clean_baseline_apply_check": "passed",
                    "captured_at": now(),
                },
            )
        explicit_usage = _explicit_component_usage(container) if bundle is not None else []
        trajectory_identity = runtime_identity
        trajectory_path = out / "trajectory.json"
        if trajectory_path.is_file():
            trajectory = read(trajectory_path)
            trajectory_identity = trajectory.get("info", {}).get(
                "runtime_identity", runtime_identity
            )
        return {
            "instance_id": task_id,
            "arm": arm,
            "status": status,
            "patch": patch,
            "patch_available": bool(patch),
            "finished_at": now(),
            "started_at": started_at,
            "elapsed_seconds": time.monotonic() - started_clock,
            "component_usage": _merged_usage(backend_result.messages, explicit_usage),
            "model_calls": backend_result.model_calls,
            "input_tokens": backend_result.input_tokens,
            "output_tokens": backend_result.output_tokens,
            "reported_cost_usd": backend_result.reported_cost_usd,
            "session_id": backend_result.session_id,
            "completion_validated": backend_result.completion_validated and status == SUBMITTED,
            "agent_backend": backend_name,
            "runtime_identity": runtime_identity,
            "run_identity": trajectory_identity,
            "network_proof": proof,
            "error": error if status != SUBMITTED else None,
            **({"diagnostics": extra} if extra else {}),
        }
    finally:
        try:
            container.remove(force=True)
        except Exception as exc:
            write(
                out / "cleanup_error.json",
                {"error": str(exc), "recorded_at": now()},
            )
