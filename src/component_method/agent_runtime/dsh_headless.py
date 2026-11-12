"""Pinned DeepSeek Harness headless backend with a container-only Bash tool."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any

from .contracts import AgentRunRequest, AgentRunResult
from .events import result_from_dsh_events
from .status import AGENT_PROCESS_ERROR, RESUME_ERROR, TIMEOUT


PINNED_DSH_VERSION = "0.2.2-rc.1"
PINNED_NODE_VERSION = "24.9.0"
PROFILE_NAME = "component-method"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DshHeadlessBackend:
    """Run DSH as a host subprocess while exposing only the controlled tool."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        repository_root: Path | None = None,
        dsh_root: Path | None = None,
        dsh_bin: Path | None = None,
        node_bin: Path | None = None,
        host_environment: Mapping[str, str] | None = None,
        request_timeout_ms: int = 600_000,
        max_retries: int = 2,
        compatibility: Mapping[str, Any] | None = None,
        context_window: int = 131_072,
        max_output_tokens: int = 8_192,
        runtime_activation: str = "",
    ) -> None:
        default_repository = Path(__file__).resolve().parents[3]
        self.repository_root = (repository_root or default_repository).resolve()
        self.dsh_root = Path(dsh_root or self.repository_root / "dsh").resolve()
        self.dsh_bin = Path(
            dsh_bin or self.dsh_root / "node_modules" / ".bin" / "dsh"
        ).resolve()
        selected_node = node_bin or (
            Path(value) if (value := os.environ.get("COMPONENT_DSH_NODE_BIN")) else None
        )
        if selected_node is None:
            found = shutil.which("node")
            selected_node = Path(found) if found else Path("node")
        self.node_bin = Path(selected_node).expanduser().resolve()
        self.api_key = api_key
        self.base_url = base_url
        self.host_environment = dict(
            os.environ if host_environment is None else host_environment
        )
        self.request_timeout_ms = request_timeout_ms
        self.max_retries = max_retries
        self.compatibility = dict(compatibility or {})
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.runtime_activation = runtime_activation.strip()
        self.profile_patch = self.dsh_root / "profiles" / PROFILE_NAME / "cordis.patch.yml"
        self.plugin_bundle = self.dsh_root / "plugins" / "controlled-bash" / "dist" / "index.js"
        self.lockfile = self.dsh_root / "package-lock.json"
        self.package_json = self.dsh_root / "package.json"

    def _node_version(self) -> str | None:
        try:
            completed = subprocess.run(
                [str(self.node_bin), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return completed.stdout.strip().removeprefix("v") or None

    def _dsh_version(self) -> str | None:
        try:
            payload = json.loads(self.package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = payload.get("dependencies", {}).get("@deepseek-ai/dsh")
        return value if isinstance(value, str) else None

    def runtime_identity(self) -> dict[str, str | None]:
        def digest(path: Path) -> str | None:
            return _sha256(path) if path.is_file() else None

        return {
            "backend": "dsh",
            "dsh_version": self._dsh_version(),
            "node_version": self._node_version(),
            "lockfile_sha256": digest(self.lockfile),
            "profile_sha256": digest(self.profile_patch),
            "plugin_bundle_sha256": digest(self.plugin_bundle),
        }

    def validate_runtime(self) -> None:
        if self._node_version() != PINNED_NODE_VERSION:
            raise RuntimeError(
                f"DSH requires Node.js {PINNED_NODE_VERSION}; found {self._node_version() or 'none'}"
            )
        if self._dsh_version() != PINNED_DSH_VERSION:
            raise RuntimeError(
                f"DSH package must be {PINNED_DSH_VERSION}; found {self._dsh_version() or 'none'}"
            )
        for path, description in (
            (self.dsh_bin, "DSH executable"),
            (self.lockfile, "DSH lockfile"),
            (self.profile_patch, "DSH profile patch"),
            (self.plugin_bundle, "controlled-bash plugin bundle"),
        ):
            if not path.is_file():
                raise RuntimeError(f"{description} is missing: {path}")

    def _minimal_environment(self, request: AgentRunRequest, dsh_home: Path) -> dict[str, str]:
        process_home = request.output_dir / "agent_home"
        process_tmp = request.output_dir / "tmp"
        process_home.mkdir(parents=True, exist_ok=True)
        process_tmp.mkdir(parents=True, exist_ok=True)
        environment = {
            "PATH": ":".join(
                dict.fromkeys(
                    [
                        str(self.node_bin.parent),
                        "/usr/local/bin",
                        "/usr/bin",
                        "/bin",
                    ]
                )
            ),
            "HOME": str(process_home),
            "XDG_CONFIG_HOME": str(process_home / ".config"),
            "TMPDIR": str(process_tmp),
            "DSH_HOME": str(dsh_home),
            "DSH_TELEMETRY_MODE": "DISABLED",
            "OPENAI_API_KEY": self.api_key,
            "OPENAI_BASE_URL": self.base_url,
            "COMPONENT_DSH_MODEL": request.model,
            "COMPONENT_DSH_REQUEST_TIMEOUT_MS": str(self.request_timeout_ms),
            "COMPONENT_DSH_MAX_RETRIES": str(self.max_retries),
            "COMPONENT_DSH_COMPAT_JSON": json.dumps(
                self.compatibility, sort_keys=True, separators=(",", ":")
            ),
            "COMPONENT_DSH_CONTEXT_WINDOW": str(self.context_window),
            "COMPONENT_DSH_MAX_OUTPUT_TOKENS": str(self.max_output_tokens),
            "COMPONENT_DSH_SYSTEM_PROMPT": request.system_prompt,
            "COMPONENT_DSH_CONTAINER_NAME": request.container_name,
            "COMPONENT_DSH_ALLOWED_CWDS": json.dumps([request.container_cwd]),
            "COMPONENT_DSH_DEFAULT_CWD": request.container_cwd,
            "COMPONENT_DSH_COMMAND_TIMEOUT": str(request.command_timeout_seconds),
            "COMPONENT_DSH_SUBMISSION_MODE": request.submission_mode,
            "COMPONENT_DSH_SUBMISSION_ROLE": request.submission_role or request.role,
            "COMPONENT_DSH_VALIDATED_SUBMISSION_PATH": str(
                request.output_dir / "validated_submission.json"
            ),
            "PYTHONUNBUFFERED": "1",
        }
        if request.submission_checker_command is not None:
            if not request.submission_checker_command or any(
                not isinstance(argument, str) or not argument
                for argument in request.submission_checker_command
            ):
                raise ValueError(
                    "submission_checker_command must contain non-empty strings"
                )
            environment["COMPONENT_DSH_CHECKER_COMMAND_JSON"] = json.dumps(
                list(request.submission_checker_command),
                separators=(",", ":"),
            )
        if self.runtime_activation:
            environment["COMPONENT_DSH_RUNTIME_ACTIVATION"] = self.runtime_activation
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
        ):
            if value := self.host_environment.get(key):
                environment[key] = value
        return environment

    def build_command(self, request: AgentRunRequest) -> list[str]:
        command = [
            str(self.dsh_bin),
            "--profile",
            PROFILE_NAME,
            "--patch",
            str(self.profile_patch),
            "--json",
        ]
        if request.resume_session_id:
            command.extend(["--session-id", request.resume_session_id])
        command.append("-")
        return command

    def _ensure_profile(self, dsh_home: Path, environment: Mapping[str, str]) -> None:
        manifest = dsh_home / "profiles" / PROFILE_NAME / "package.json"
        if not manifest.is_file():
            completed = subprocess.run(
                [
                    str(self.dsh_bin),
                    "--profile",
                    PROFILE_NAME,
                    "--from-default-profile",
                    "headless",
                    "--dump-config",
                ],
                cwd=self.dsh_root,
                env=dict(environment),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode != 0 or not manifest.is_file():
                detail = completed.stderr.strip() or "profile manifest was not created"
                raise RuntimeError(f"could not initialize DSH profile: {detail}")

        plugin_source = self.dsh_root / "plugins" / "controlled-bash"
        plugin_link = (
            manifest.parent
            / "node_modules"
            / "@component-method"
            / "dsh-controlled-bash"
        )
        if plugin_link.is_symlink():
            if plugin_link.resolve() != plugin_source.resolve():
                raise RuntimeError(f"DSH profile plugin link points elsewhere: {plugin_link}")
            return
        if plugin_link.exists():
            raise RuntimeError(f"DSH profile plugin path is not a symlink: {plugin_link}")
        plugin_link.parent.mkdir(parents=True, exist_ok=True)
        plugin_link.symlink_to(plugin_source, target_is_directory=True)

    def _write_trajectory(self, request: AgentRunRequest, result: AgentRunResult) -> None:
        identity = self.runtime_identity()
        identity.update(
            {
                "system_prompt_sha256": hashlib.sha256(
                    request.system_prompt.encode("utf-8")
                ).hexdigest(),
                "task_prompt_sha256": hashlib.sha256(
                    request.task_prompt.encode("utf-8")
                ).hexdigest(),
                "model_route_sha256": hashlib.sha256(
                    json.dumps(
                        {
                            "base_url": self.base_url,
                            "model": request.model,
                            "request_timeout_ms": self.request_timeout_ms,
                            "max_retries": self.max_retries,
                            "compatibility": self.compatibility,
                            "context_window": self.context_window,
                            "max_output_tokens": self.max_output_tokens,
                            "runtime_activation": self.runtime_activation,
                            "submission_checker_command": (
                                list(request.submission_checker_command)
                                if request.submission_checker_command is not None
                                else None
                            ),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
        )
        trajectory = {
            "messages": result.messages,
            "tool_calls": result.tool_calls,
            "info": {
                "exit_status": result.status,
                "submission": result.final_output,
                "result": result.error,
                "session_id": result.session_id,
                "completion_validated": result.completion_validated,
                "model_stats": {
                    "api_calls": result.model_calls,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "instance_cost": result.reported_cost_usd,
                },
                "runtime_identity": identity,
            },
        }
        (request.output_dir / "trajectory.json").write_text(
            json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (request.output_dir / "dsh_session.json").write_text(
            json.dumps(
                {
                    "session_id": result.session_id,
                    "resume_session_id": request.resume_session_id,
                    "dsh_home": str(request.output_dir / "dsh_home"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        prompt_dir = request.output_dir / "prompt_input"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "system.txt").write_text(request.system_prompt, encoding="utf-8")
        (prompt_dir / "user.txt").write_text(request.task_prompt, encoding="utf-8")
        events_path = request.output_dir / "dsh_events.jsonl"
        current_events_path = request.output_dir / ".dsh_events.current.jsonl"
        validated_path = request.output_dir / "validated_submission.json"
        dsh_home = request.output_dir / "dsh_home"
        environment = self._minimal_environment(request, dsh_home)
        log_mode = "a" if request.resume_session_id else "w"
        validated_path.unlink(missing_ok=True)
        if not request.resume_session_id:
            events_path.unlink(missing_ok=True)
        current_events_path.unlink(missing_ok=True)

        try:
            self.validate_runtime()
            if request.resume_session_id and not dsh_home.is_dir():
                raise FileNotFoundError("DSH_HOME is missing for the requested session resume")
            self._ensure_profile(dsh_home, environment)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            status = RESUME_ERROR if request.resume_session_id else AGENT_PROCESS_ERROR
            result = AgentRunResult(
                status=status,
                session_id=request.resume_session_id,
                final_output="",
                messages=[],
                tool_calls=[],
                model_calls=0,
                input_tokens=None,
                output_tokens=None,
                reported_cost_usd=None,
                completion_validated=False,
                error=str(exc),
            )
            self._write_trajectory(request, result)
            return result

        return_code: int | None = None
        timed_out = False
        step_limited = False
        stdout = ""
        stderr = ""
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                self.build_command(request),
                cwd=self.dsh_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            observed_step = 0
            observed_lock = threading.Lock()

            def read_stdout() -> None:
                nonlocal observed_step
                assert process.stdout is not None
                for line in process.stdout:
                    stdout_lines.append(line)
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "status" and event.get("phase") == "step_end":
                        step = event.get("step")
                        if isinstance(step, int) and not isinstance(step, bool):
                            with observed_lock:
                                observed_step = max(observed_step, step)

            def read_stderr() -> None:
                assert process.stderr is not None
                stderr_lines.extend(process.stderr)

            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            assert process.stdin is not None
            process.stdin.write(request.task_prompt)
            process.stdin.close()
            deadline = (
                time.monotonic() + request.total_timeout_seconds
                if request.total_timeout_seconds is not None
                else None
            )
            while process.poll() is None:
                with observed_lock:
                    current_step = observed_step
                if request.step_limit is not None and current_step >= request.step_limit:
                    step_limited = True
                    process.kill()
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    process.kill()
                    break
                time.sleep(0.05)
            process.wait()
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            return_code = process.returncode
        except OSError as exc:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            stderr = f"could not launch DSH: {exc}"
            return_code = 1

        normalized_stdout = stdout
        if normalized_stdout and not normalized_stdout.endswith("\n"):
            normalized_stdout += "\n"
        current_events_path.write_text(normalized_stdout, encoding="utf-8")
        with events_path.open("a", encoding="utf-8") as event_file:
            event_file.write(normalized_stdout)
        with (request.output_dir / "agent.log").open(log_mode, encoding="utf-8") as log_file:
            if stderr:
                log_file.write(stderr)
                if not stderr.endswith("\n"):
                    log_file.write("\n")

        result = result_from_dsh_events(
            current_events_path,
            return_code=return_code,
            validated_submission_path=validated_path,
            submission_mode=request.submission_mode,
            expected_role=request.submission_role or request.role,
            expected_container=request.container_name,
            resume_requested=request.resume_session_id is not None,
            timed_out=timed_out,
            step_limited=step_limited,
            step_limit=request.step_limit,
            fallback_error=(
                f"DSH exceeded {request.total_timeout_seconds} seconds"
                if timed_out
                else (
                    f"DSH reached the configured step limit of {request.step_limit}"
                    if step_limited
                    else (stderr.strip() or None)
                )
            ),
        )
        if timed_out and result.status != TIMEOUT:
            result = AgentRunResult(
                status=TIMEOUT,
                session_id=result.session_id,
                final_output=result.final_output,
                messages=result.messages,
                tool_calls=result.tool_calls,
                model_calls=result.model_calls,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                reported_cost_usd=result.reported_cost_usd,
                completion_validated=False,
                error=result.error,
            )
        self._write_trajectory(request, result)
        current_events_path.unlink(missing_ok=True)
        return result
