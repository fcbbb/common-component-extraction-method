"""Run isolated MiniSWE tasks over read-only community or repository snapshots."""

from __future__ import annotations

import base64
import importlib.util
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..workspace import COMPONENT_DIRECTORY, TASK_RUNTIME_ACTIVATION, prepare_component_mount
from ..submission import CHECKER_PATH, OUTPUT_DIRECTORY, file_submission_instructions, load_submission

from ..context.support import write_json


AGENT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "agent_configs"
AGENT_ROLES = ("extraction", "review", "repair", "proposal", "proposal_review")


def agent_config_paths(role: str) -> tuple[Path, Path]:
    """Return the common runtime protocol and the explicit role's system config."""
    if role not in AGENT_ROLES:
        raise ValueError(f"unsupported component agent role: {role}")
    return AGENT_CONFIG_DIR / "runtime.yaml", AGENT_CONFIG_DIR / f"{role}.yaml"


def _agent_config_identity(default_config: Path, role: str) -> str:
    digest = hashlib.sha256()
    for path in (default_config, *agent_config_paths(role)):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def default_agent_config_identities() -> dict[str, str] | None:
    """Read effective stage configs before deciding whether a bundle can be reused."""
    spec = importlib.util.find_spec("minisweagent")
    if not spec or not spec.submodule_search_locations:
        return None
    default = Path(next(iter(spec.submodule_search_locations))) / "config" / "mini.yaml"
    return {role: _agent_config_identity(default, role) for role in ("extraction", "review")}


def _task_visible_volumes(
    workspace: Path, output_dir: Path, component_workspace: Path | None = None,
    submission_directory: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Expose the supplied workspace while hiding pristine image source."""
    hidden_pristine = output_dir / "hidden_pristine_repo"
    hidden_pristine.mkdir(parents=True, exist_ok=True)
    volumes = {
        str(workspace.resolve()): {"bind": "/testbed", "mode": "ro"},
        str(hidden_pristine.resolve()): {"bind": "/root/my_repo", "mode": "ro"},
    }
    if component_workspace is not None:
        prepare_component_mount(workspace)
        volumes[str(component_workspace.resolve())] = {"bind": COMPONENT_DIRECTORY, "mode": "ro"}
    if submission_directory is not None:
        volumes[str(submission_directory.resolve())] = {"bind": OUTPUT_DIRECTORY, "mode": "rw"}
        checker = Path(__file__).resolve().parents[1] / "submission.py"
        volumes[str(checker)] = {"bind": CHECKER_PATH, "mode": "ro"}
    return volumes


class MiniSweComponentRunner:
    """Launch an isolated MiniSWE agent with an explicit stage-specific role."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: int = 1080,
        runtime_image: str | None = None,
        repository_root: Path | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.runtime_image = runtime_image
        self.repository_root = repository_root.resolve() if repository_root is not None else None
        if self.repository_root is not None and not self.repository_root.is_dir():
            raise FileNotFoundError(f"task repository does not exist: {self.repository_root}")

        miniswe_spec = importlib.util.find_spec("minisweagent")
        if not miniswe_spec or not miniswe_spec.submodule_search_locations:
            raise RuntimeError(
                "mini-swe-agent is not importable; run with "
                "'uv run --with mini-swe-agent --with httpx[socks] ...'"
            )
        package_dir = Path(next(iter(miniswe_spec.submodule_search_locations)))

        try:
            import docker
            from component_method.task_execution.runtime_support import build_helpers
        except ImportError as exc:
            raise RuntimeError(
                "MiniSWE region exploration requires the packaged Docker dependencies"
            ) from exc

        self.gold = build_helpers
        self.docker_client = docker.from_env()
        self.image_id: str | None = None
        self.image_tag: str | None = None
        self._image_lock = threading.Lock()
        self.default_config = package_dir / "config" / "mini.yaml"

    def _config_arguments(self, role: str) -> list[str]:
        paths = (self.default_config, *agent_config_paths(role))
        return [argument for path in paths for argument in ("--config", str(path))]

    def agent_config_identity(self, role: str) -> str:
        return _agent_config_identity(self.default_config, role)

    def _agent_command(self, task: str, trajectory: Path, configs: list[str]) -> list[str]:
        """Allow callers to adapt the launcher to their installed agent API."""
        return [
            sys.executable, "-m", "minisweagent.run.mini", "--model", self.model,
            "--task", task, "--yolo", "--exit-immediately", "--environment-class",
            self.gold.COMPONENT_AGENT_ENVIRONMENT_CLASS, "--output", str(trajectory), *configs,
        ]

    def _ensure_image(self) -> None:
        with self._image_lock:
            if self.image_tag is None:
                if self.runtime_image:
                    self.image_id = self.docker_client.images.get(self.runtime_image).id
                    self.image_tag = self.runtime_image
                else:
                    self.image_id, self.image_tag = self.gold._ensure_image(self.docker_client)

    def repository_context_identity(self) -> str | None:
        """Account for all readable task files, including non-primary dependencies."""
        repo = getattr(self, "repository_root", None)
        if repo is None:
            return None
        digest = hashlib.sha256()
        for current, dirs, filenames in os.walk(repo, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name not in {".git", ".components", "__pycache__"})
            for name in sorted(filenames):
                path = Path(current) / name
                if path.is_symlink():
                    raise ValueError(f"task repository context contains a symlink: {path.relative_to(repo)}")
                digest.update(path.relative_to(repo).as_posix().encode())
                digest.update(b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def _configure_runtime(self, container: Any, output_dir: Path, child_env: dict[str, str]) -> None:
        if not getattr(self, "runtime_image", None):
            return
        child_env["COMPONENT_RUNTIME_ACTIVATION"] = TASK_RUNTIME_ACTIVATION
        probe = (
            "import importlib.metadata as m,json,sys; "
            "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,"
            "'python_version':sys.version,'packages':sorted((d.metadata['Name'],d.version) "
            "for d in m.distributions() if d.metadata['Name'])}))"
        )
        import shlex
        result = container.exec_run(
            ["/bin/bash", "-lc", TASK_RUNTIME_ACTIVATION + " && python -c " + shlex.quote(probe)],
            user="10001:10001", environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "/testbed"},
        )
        if result.exit_code:
            raise RuntimeError("task Python environment could not be activated; no generic fallback is used")
        runtime = json.loads(result.output.decode())
        runtime.update(image_id=self.image_id, kind="task_image", activation=TASK_RUNTIME_ACTIVATION)
        write_json(output_dir / "runtime_environment.json", runtime)

    def _write_workspace(
        self,
        region_dir: Path,
        primary_files: list[str],
        context_files: list[str],
        sources: dict[str, str],
        metadata: dict[str, Any],
        *,
        write_region_context: bool = True,
    ) -> Path:
        workspace = region_dir / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        for file_id in sorted(set(primary_files) | set(context_files)):
            target = workspace / file_id
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sources[file_id], encoding="utf-8")
        if write_region_context:
            write_json(workspace / "region_context.json", metadata)
        return workspace

    def _task_prompt(self, system_prompt: str, metadata: dict[str, Any]) -> str:
        summary = {
            "region_id": metadata["region_id"],
            "primary_file_count": len(metadata["primary_files"]),
            "boundary_context_file_count": len(metadata["boundary_context_files"]),
            "cross_region_call_relationship_count": len(metadata["call_relationships"]),
            "cross_region_dependency_relationship_count": len(metadata["dependency_relationships"]),
            "gaps": metadata["gaps"],
        }
        return (
            system_prompt.strip()
            + "\n\nRegion summary:\n"
            + json.dumps(summary, ensure_ascii=False, indent=2)
            + "\n\nFull region context:\n" + json.dumps(metadata, ensure_ascii=False, indent=2)
            + "\n\nExplore the read-only snapshot over "
              "multiple shell turns; inspect every primary file. Boundary context "
              "files can help identify cross-region members. Your checked_files "
              "array must list every primary file exactly once and must not include "
              "context files. Keep source files read-only. Write the requested metadata "
              "and component implementations using the file submission protocol."
        )

    def run_region(
        self,
        *,
        region_id: str,
        region_payload: dict[str, Any],
        sources: dict[str, str],
        system_prompt: str,
        output_dir: Path,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        primary_files = list(region_payload["primary_files"])
        primary_set = set(primary_files)
        context_files = sorted({
            file_id
            for item in region_payload["call_relationships"]
            for file_id in (item["caller_file"], item["callee_file"])
            if file_id not in primary_set
        } | {
            file_id
            for item in region_payload["dependency_relationships"]
            for file_id in (item["source_file"], item["target_file"])
            if file_id not in primary_set
        })
        metadata = {
            "region_id": region_id,
            "primary_files": primary_files,
            "boundary_context_files": context_files,
            "call_relationships": region_payload["call_relationships"],
            "dependency_relationships": region_payload["dependency_relationships"],
            "gaps": region_payload["gaps"],
        }
        write_json(output_dir / "discover_input.json", metadata)
        workspace = self._write_workspace(
            output_dir,
            primary_files,
            context_files,
            sources,
            metadata,
        )
        task = self._task_prompt(system_prompt, metadata)
        (output_dir / "agent_task.txt").write_text(task, encoding="utf-8")

        result = self.run_workspace_agent(
            workspace_root=getattr(self, "repository_root", None) or workspace,
            task=task, output_dir=output_dir, task_label=f"region-{region_id}",
            agent_role="extraction",
        )
        write_json(output_dir / "discover.json", result)
        return result

    def run_workspace_agent(
        self,
        *,
        workspace_root: Path,
        task: str,
        output_dir: Path,
        task_label: str,
        agent_role: str = "extraction",
        component_workspace: Path | None = None,
    ) -> dict[str, Any]:
        """Run one tool-using agent against exactly the caller's read-only workspace."""
        config_arguments = self._config_arguments(agent_role)
        config_identity = self.agent_config_identity(agent_role)
        workspace_root = workspace_root.expanduser().resolve()
        if not workspace_root.is_dir():
            raise FileNotFoundError(f"agent workspace does not exist: {workspace_root}")
        output_dir.mkdir(parents=True, exist_ok=True)
        task = task.rstrip() + file_submission_instructions()
        (output_dir / "agent_task.txt").write_text(task, encoding="utf-8")
        task_argument = task
        mount_task_file = len(task.encode("utf-8")) > 32_000
        if mount_task_file:
            task_argument = (
                "Read /tmp/component_task.txt and follow its instructions exactly. "
                "Write the requested files and manifest to /component-output."
            )
        self._ensure_image()

        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in task_label)[:48]
        container_name = f"component-{safe_label}-{uuid.uuid4().hex[:10]}"
        trajectory_path = output_dir / "trajectory.json"
        previous_submission_dirs = sorted(
            path for path in (output_dir / "file_submissions").glob("*") if path.is_dir()
        )
        resume_trajectory = None
        previous = None
        if trajectory_path.is_file() and not (output_dir / "agent_result.json").exists():
            previous = json.loads(trajectory_path.read_text(encoding="utf-8"))
            if previous.get("messages") and previous.get("info", {}).get("exit_status") != "Submitted":
                if len(previous_submission_dirs) != 1:
                    raise RuntimeError("incomplete agent output has no unique submission directory")
                resume_trajectory = trajectory_path
        if (
            resume_trajectory is not None
            and previous.get("info", {}).get("exit_status") == "LimitsExceeded"
            and any(
                "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in message.get("content", "")
                for message in previous.get("messages", [])[-20:]
            )
        ):
            submission_directory = previous_submission_dirs[0]
            result = load_submission(submission_directory, agent_role)
            stats = previous.get("info", {}).get("model_stats", {})
            write_json(
                output_dir / "agent_status.json",
                {
                    "return_code": 0,
                    "exit_status": "RecoveredValidatedFiles",
                    "reported_cost_usd": float(stats.get("instance_cost") or 0),
                    "api_calls": int(stats.get("api_calls") or 0),
                    "model": self.model,
                    "container_image_id": self.image_id,
                    "container_network": "none",
                    "workspace_mount": "read-only",
                    "workspace_scope": safe_label,
                    "agent_role": agent_role,
                    "agent_config_identity": config_identity,
                    "submission_transport": "files",
                    "submission_directory": str(submission_directory),
                    "submission_recovered": True,
                },
            )
            write_json(output_dir / "agent_result.json", result)
            return result
        command = self._agent_command(task_argument, trajectory_path, config_arguments)
        child_env = self.gold._minimal_agent_env(
            run_dir=output_dir,
            container_name=container_name,
            api_key=self.api_key,
            base_url=self.base_url,
        )
        child_env["COMPONENT_OUTPUT_ROLE"] = agent_role
        if resume_trajectory is not None:
            child_env["COMPONENT_RESUME_TRAJECTORY"] = str(resume_trajectory)
            submission_directory = previous_submission_dirs[0]
        else:
            submission_directory = output_dir / "file_submissions" / uuid.uuid4().hex
            submission_directory.mkdir(parents=True)
            submission_directory.chmod(0o777)
        container = None
        try:
            container = self.docker_client.containers.create(
                image=self.image_tag,
                entrypoint=[],
                name=container_name,
                command=["sleep", "infinity"],
                working_dir="/testbed",
                volumes=_task_visible_volumes(workspace_root, output_dir, component_workspace, submission_directory),
                network_mode="none",
                read_only=True,
                tmpfs={"/tmp": "rw,nosuid,nodev,size=512m,mode=1777"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=128,
                mem_limit="6g",
                labels={"featurebench.component_discovery.agent": safe_label},
            )
            container.start()
            self.gold._verify_isolated_container(container)
            self._configure_runtime(container, output_dir, child_env)
            if mount_task_file:
                task_bytes = (output_dir / "agent_task.txt").read_bytes()
                task_path = "/tmp/component_task.txt"
                reset = container.exec_run(["sh", "-c", f": > {task_path}"])
                if reset.exit_code != 0:
                    raise RuntimeError("could not initialize the long agent task in container /tmp")
                chunk_bytes = 6_000
                for offset in range(0, len(task_bytes), chunk_bytes):
                    encoded = base64.b64encode(
                        task_bytes[offset:offset + chunk_bytes]
                    ).decode("ascii")
                    result = container.exec_run([
                        "sh",
                        "-c",
                        'printf "%s" "$1" | base64 -d >> "$2"',
                        "component-task-writer",
                        encoded,
                        task_path,
                    ])
                    if result.exit_code != 0:
                        output = result.output
                        if isinstance(output, bytes):
                            output = output.decode("utf-8", errors="replace")
                        raise RuntimeError(
                            "could not write the long agent task in container /tmp: "
                            f"{output}"
                        )
            log_path = output_dir / "agent.log"
            log_mode = "a" if resume_trajectory is not None else "w"
            with log_path.open(log_mode, encoding="utf-8") as log_file:
                process = subprocess.Popen(
                    command,
                    cwd=self.gold.FEATUREBENCH_ROOT,
                    env=child_env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    return_code = process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise TimeoutError(
                        f"MiniSWE agent exceeded {self.timeout_seconds} seconds"
                    )

            submission, exit_status, cost, api_calls = self.gold._extract_submission(
                trajectory_path
            )
            (output_dir / "submission.txt").write_text(submission, encoding="utf-8")
            write_json(
                output_dir / "agent_status.json",
                {
                    "return_code": return_code,
                    "exit_status": exit_status,
                    "reported_cost_usd": cost,
                    "api_calls": api_calls,
                    "model": self.model,
                    "container_image_id": self.image_id,
                    "container_network": "none",
                    "workspace_mount": "read-only",
                    "workspace_scope": safe_label,
                    "agent_role": agent_role,
                    "agent_config_identity": config_identity,
                    "submission_transport": "files",
                    "submission_directory": str(submission_directory),
                },
            )
            if return_code != 0 or exit_status != "Submitted":
                raise RuntimeError(
                    "MiniSWE agent did not submit a result "
                    f"(return_code={return_code}, exit_status={exit_status})"
                )
            result = load_submission(submission_directory, agent_role)
            write_json(output_dir / "agent_result.json", result)
            return result
        finally:
            if container is not None:
                try:
                    # Nested deliverable directories are created by uid 10001.
                    # Leave them removable by the host owner of the output bind.
                    # find does not follow symlinks and excludes the host root.
                    container.exec_run([
                        "find", OUTPUT_DIRECTORY, "-mindepth", "1", "-type", "d",
                        "-exec", "chmod", "a+rwx", "{}", "+",
                    ], user="10001:10001")
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    def run_validation_agent(
        self,
        *,
        repo_root: Path,
        component_payload: dict[str, Any],
        system_prompt: str,
        output_dir: Path,
    ) -> dict[str, Any]:
        """Author a smoke test using the same checked file submission protocol."""
        task = (
            system_prompt.strip()
            + "\n\nComponent to validate:\n"
            + json.dumps(component_payload, ensure_ascii=False, indent=2)
            + "\n\nInspect /testbed read-only for grounded calls and source citations. "
              "Write the test file inside /component-output, with run(common). "
              "The manifest has status ready|no_cases, reason, test_file and sources."
        )
        return self.run_workspace_agent(
            workspace_root=repo_root, task=task, output_dir=output_dir,
            task_label="component-validation", agent_role="review",
        )


# Preserve the existing regional caller interface.
MiniSweRegionRunner = MiniSweComponentRunner

OFFICIAL_IMAGE_ACTIVATION = "export PATH=/usr/local/bin:/usr/bin:/bin; export PYTHONPYCACHEPREFIX=/tmp/pycache"
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TASK_EXECUTION = PACKAGE_ROOT / "task_execution"


class OfficialImageExtractionRunner(MiniSweComponentRunner):
    """使用任务镜像和发布配置运行组件抽取。"""

    def __init__(
        self, *, request_timeout: int = 600, **kwargs
    ) -> None:
        self.request_timeout = request_timeout
        super().__init__(**kwargs)

    @property
    def component_config(self) -> Path:
        return TASK_EXECUTION / "config" / "component.yaml"

    @property
    def pricing_config(self) -> Path:
        return TASK_EXECUTION / "config" / "pricing.json"

    @property
    def model_adapter(self) -> Path:
        return TASK_EXECUTION / "adapters" / "component_agent.py"

    @property
    def runtime_config(self) -> Path:
        return PACKAGE_ROOT / "component_build" / "agent_configs" / "runtime.yaml"

    def _configure_runtime(self, container, output_dir, child_env) -> None:
        child_env["COMPONENT_RUNTIME_OFFICIAL_IMAGE_ACTIVATION"] = OFFICIAL_IMAGE_ACTIVATION
        child_env["REQUEST_TIMEOUT"] = str(self.request_timeout)
        probe = """import json,sys
try:
 import importlib.metadata as m
 packages=sorted((d.metadata['Name'],d.version) for d in m.distributions() if d.metadata['Name'])
except ImportError:
 import pkg_resources
 packages=sorted((d.project_name,d.version) for d in pkg_resources.working_set)
print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'python_version':sys.version,'packages':packages}))
"""
        result = container.exec_run(
            ["/bin/bash", "-lc", OFFICIAL_IMAGE_ACTIVATION + " && python -c " + shlex.quote(probe)],
            user="10001:10001",
            environment={
                "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": "/testbed",
            },
            demux=True,
        )
        stdout, stderr = result.output
        if stderr:
            (output_dir / "runtime_probe.stderr.txt").write_bytes(stderr)
        if result.exit_code:
            raise RuntimeError("official Python environment inventory failed")
        runtime = json.loads((stdout or b"").decode())
        runtime.update(image_id=self.image_id, kind="task_image", activation=OFFICIAL_IMAGE_ACTIVATION)
        (output_dir / "runtime_environment.json").write_text(
            json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _agent_command(self, task, trajectory, configs):
        merged = {}

        def merge(target, other):
            for key, value in other.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    merge(target[key], value)
                else:
                    target[key] = value

        for index, argument in enumerate(configs):
            if argument == "--config":
                merge(merged, yaml.safe_load(Path(configs[index + 1]).read_text()))
        official = yaml.safe_load(self.default_config.read_text())
        snapshot = trajectory.parent / "prompt_input"
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "user.txt").write_text(task, encoding="utf-8")
        (snapshot / "system.txt").write_text(
            official["agent"]["system_template"]
            + "\n\n"
            + merged["agent"]["system_template"],
            encoding="utf-8",
        )
        return [
            sys.executable,
            str(self.model_adapter),
            "--model",
            self.model,
            "--task",
            task,
            "--output",
            str(trajectory),
            "--input-snapshot",
            str(snapshot),
            *configs,
        ]

    def _config_arguments(self, role):
        _, role_config = agent_config_paths(role)
        paths = (self.default_config, self.runtime_config, role_config, self.component_config)
        return [argument for path in paths for argument in ("--config", str(path))]

    def agent_config_identity(self, role):
        digest = hashlib.sha256()
        digest.update(OFFICIAL_IMAGE_ACTIVATION.encode())
        digest.update(str(self.request_timeout).encode())
        for path in (
            self.default_config,
            self.runtime_config,
            agent_config_paths(role)[1],
            self.component_config,
            self.model_adapter,
            TASK_EXECUTION / "adapters" / "action_protocol.py",
            self.pricing_config,
        ):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()
