#!/usr/bin/env python3
"""Run DSH on the remote execution host, over SSH.

Some scenarios can only be executed where the target toolchain lives.  The
``cuda_to_musa`` box is a plain Ubuntu container with an MTT S4000, no Docker
daemon, no ``CAP_SYS_ADMIN`` and therefore no place to nest a container.  The
old design kept DSH on this host and mirrored a second workspace back and forth
through an API shim; the two copies were the reason agent output could go
missing.

This backend removes the second copy.  It ships one attempt directory to the
remote host, runs the pinned DSH there with the host-shell profile (stock
``bash`` tool instead of the Docker-backed ``controlled_bash``), streams the
``--json`` event log back into the local attempt directory, and pulls the
remote agent directory back for evidence.  The remote host is the single
filesystem for the attempt: the agent, the method tools and the judge all see
the same files.

The controller cannot put a multi-line system prompt on an ``ssh`` command
line, so the environment is shipped as JSON and applied by
``tools/remote_launch.py``, which ``exec``s DSH with it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

import remote_setup as rs

if TYPE_CHECKING:  # the component_method package lives in the repository's src/
    from component_method.agent_runtime.contracts import AgentRunRequest, AgentRunResult


def _runtime_modules() -> Tuple[Any, ...]:
    """Import the controller's DSH types on first use.

    ``migration_trial`` imports this module before it resolves ``--repository-root``
    and puts that repository's ``src`` on ``sys.path``, so the imports cannot
    happen at module import time.
    """
    from component_method.agent_runtime import events as events_module
    from component_method.agent_runtime import status as status_module
    from component_method.agent_runtime import dsh_headless

    return (
        dsh_headless.PINNED_DSH_VERSION,
        dsh_headless.PINNED_NODE_VERSION,
        events_module.result_from_dsh_events,
        status_module.AGENT_PROCESS_ERROR,
        status_module.RESUME_ERROR,
        status_module.TIMEOUT,
    )


def _sha256_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _quote(value: str) -> str:
    return shlex.quote(value)


class RemoteDshBackend:
    """Execute the pinned DSH on the remote execution plane."""

    def __init__(
        self,
        *,
        remote_config: Mapping[str, Any],
        api_key: str,
        base_url: str,
        repository_root: Path,
        remote_repo: Optional[str] = None,
        profile_name: str = "component-method-host",
        request_timeout_ms: int = 600_000,
        max_retries: int = 2,
        compatibility: Mapping[str, Any] | None = None,
        context_window: int = 262_144,
        max_output_tokens: int = 8_192,
        runtime_activation: str = "",
    ) -> None:
        self.config: Dict[str, Any] = dict(remote_config)
        self.repository_root = Path(repository_root).resolve()
        root = str(self.config.get("remote_root") or "/root/migration-bench").rstrip("/")
        self.remote_root = root
        self.remote_repo = (remote_repo or f"{root}/repo").rstrip("/")
        self.remote_dsh_root = f"{self.remote_repo}/dsh"
        self.remote_node_bin = f"{root}/toolchain/node/bin/node"
        self.remote_node_dir = f"{root}/toolchain/node/bin"
        self.remote_dsh_bin = f"{self.remote_dsh_root}/node_modules/.bin/dsh"
        self.remote_launcher = (
            f"{self.remote_repo}/migration_scenario_validation/tools/remote_launch.py"
        )
        self.api_key = api_key
        self.base_url = base_url
        self.request_timeout_ms = request_timeout_ms
        self.max_retries = max_retries
        self.compatibility = dict(compatibility or {})
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.runtime_activation = runtime_activation.strip()
        self.profile_name = (profile_name or "component-method-host").strip()
        self._identity: Optional[Dict[str, Any]] = None

    # ---------------------------------------------------------------- setup --
    def _profile_patch(self, profile: str) -> str:
        return f"{self.remote_dsh_root}/profiles/{profile}/cordis.patch.yml"

    def validate_runtime(self) -> Dict[str, Any]:
        pinned_dsh, pinned_node, _, _, _, _ = _runtime_modules()
        profile = self.profile_name
        patch = self._profile_patch(profile)
        script = (
            f"set -e\n"
            f"export PATH={self.remote_node_dir}:/usr/local/bin:/usr/bin:/bin\n"
            f"{_quote(self.remote_node_bin)} --version\n"
            f"{_quote(self.remote_dsh_bin)} --version\n"
            f"test -f {_quote(patch)}\n"
            f"test -f {_quote(self.remote_launcher)}\n"
            f"sha256sum {_quote(self.remote_repo + '/dsh/package-lock.json')} "
            f"{_quote(patch)} "
            f"{_quote(self.remote_dsh_root + '/plugins/controlled-bash/dist/index.js')}\n"
        )
        rc, out = rs._ssh(self.config, script, timeout=180)
        lines = [line for line in out.strip().splitlines() if line.strip()]
        if rc != 0 or len(lines) < 5:
            raise RuntimeError(
                f"remote DSH runtime is not usable (rc={rc}): {out.strip()[-800:]}"
            )
        node_version = lines[0].strip().removeprefix("v")
        dsh_version = lines[1].strip()
        digests = {}
        for line in lines[2:5]:
            parts = line.split()
            if len(parts) == 2:
                digests[parts[1]] = parts[0]
        if node_version != pinned_node:
            raise RuntimeError(
                f"remote DSH requires Node.js {pinned_node}; "
                f"found {node_version or 'none'}"
            )
        if dsh_version != pinned_dsh:
            raise RuntimeError(
                f"remote DSH package must be {pinned_dsh}; "
                f"found {dsh_version or 'none'}"
            )
        self._identity = {
            "backend": "dsh-remote",
            "host": str(self.config.get("host") or ""),
            "node_version": node_version,
            "dsh_version": dsh_version,
            "profile_name": profile,
            "profile_sha256": digests.get(patch),
            "lockfile_sha256": digests.get(
                f"{self.remote_repo}/dsh/package-lock.json"
            ),
            "plugin_bundle_sha256": digests.get(
                f"{self.remote_dsh_root}/plugins/controlled-bash/dist/index.js"
            ),
            "repository_sha256": self._local_tree_digest(),
        }
        return dict(self._identity)

    def runtime_identity(self) -> Dict[str, Any]:
        if self._identity is not None:
            return dict(self._identity)
        try:
            return self.validate_runtime()
        except Exception as exc:  # noqa: BLE001
            return {"backend": "dsh-remote", "error": str(exc)}

    def _local_tree_digest(self) -> Optional[str]:
        """Digest of the profile + launcher as shipped, for evidence."""
        digest = hashlib.sha256()
        for path in (
            self.repository_root / "dsh" / "profiles" / self.profile_name / "cordis.patch.yml",
            self.repository_root
            / "migration_scenario_validation"
            / "tools"
            / "remote_launch.py",
        ):
            digest.update(path.name.encode("utf-8"))
            digest.update((_sha256_file(path) or "missing").encode("ascii"))
        return digest.hexdigest()

    # ------------------------------------------------------------ execution --
    def _translate(self, value: str, path_map: Sequence[Tuple[Path, str]]) -> str:
        """Rewrite a local path under a synced root to its remote location."""
        try:
            candidate = Path(value).expanduser()
        except (OSError, ValueError):
            return value
        if not candidate.is_absolute():
            return value
        resolved = candidate.resolve()
        for local_root, remote_root in path_map:
            try:
                relative = resolved.relative_to(local_root)
            except ValueError:
                continue
            return str(PurePosixPath(remote_root) / PurePosixPath(relative.as_posix()))
        return value

    def _environment(
        self,
        request: AgentRunRequest,
        remote_output: PurePosixPath,
        path_map: Sequence[Tuple[Path, str]],
        method_environment: Mapping[str, str],
    ) -> Dict[str, str]:
        def remote(path: str) -> str:
            return self._translate(path, path_map)

        remote_home = str(remote_output / "agent_home")
        environment: Dict[str, str] = {
            "PATH": f"{self.remote_node_dir}:/usr/local/bin:/usr/bin:/bin",
            "HOME": remote_home,
            "XDG_CONFIG_HOME": str(remote_output / "agent_home" / ".config"),
            "TMPDIR": str(remote_output / "tmp"),
            "DSH_HOME": str(remote_output / "dsh_home"),
            "DSH_TELEMETRY_MODE": "DISABLED",
            "OPENAI_API_KEY": self.api_key,
            "OPENAI_BASE_URL": self.base_url,
            "OPENAI_API_BASE": self.base_url,
            "MODEL_NAME": request.model,
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
            "COMPONENT_DSH_REMOTE_CWD": self.remote_dsh_root,
            "COMPONENT_DSH_AGENT_USER": str(self.config.get("agent_user") or ""),
            "COMPONENT_DSH_COMMAND_TIMEOUT": str(request.command_timeout_seconds),
            "COMPONENT_DSH_SUBMISSION_MODE": request.submission_mode,
            "COMPONENT_DSH_SUBMISSION_ROLE": request.submission_role or request.role,
            "COMPONENT_DSH_VALIDATED_SUBMISSION_PATH": str(
                remote_output / "validated_submission.json"
            ),
            "COMPONENT_DSH_METHOD_ROOT": self.remote_repo,
            "COMPONENT_DSH_OUTPUT_DIRECTORY": "/component-output",
            "COMPONENT_DSH_PYTHON_BIN": "python3",
            "COMPONENT_DSH_JOB_ROOT": str(remote_output / "method_jobs"),
            "PYTHONUNBUFFERED": "1",
        }
        if request.method_registry is not None:
            environment["COMPONENT_DSH_RUN_REGISTRY"] = remote(
                str(request.method_registry.expanduser().resolve())
            )
        if request.method_task_id:
            environment["COMPONENT_DSH_TASK_ID"] = request.method_task_id
        if request.method_offline_tasks is not None:
            environment["COMPONENT_DSH_OFFLINE_TASKS"] = remote(
                str(request.method_offline_tasks.expanduser().resolve())
            )
        if request.submission_directory is not None:
            environment["COMPONENT_DSH_OUTPUT_HOST_DIR"] = remote(
                str(request.submission_directory.expanduser().resolve())
            )
        if request.submission_checker_command is not None:
            environment["COMPONENT_DSH_CHECKER_COMMAND_JSON"] = json.dumps(
                list(request.submission_checker_command), separators=(",", ":")
            )
        if self.runtime_activation:
            environment["COMPONENT_DSH_RUNTIME_ACTIVATION"] = self.runtime_activation
        if request.repository is not None:
            environment["COMPONENT_DSH_REPOSITORY"] = remote(
                str(Path(request.repository).expanduser().resolve())
            )
        for key, value in method_environment.items():
            if value:
                environment[key] = remote(value)
        return environment

    def _command(self, profile: str, request: AgentRunRequest, remote_env: str) -> str:
        parts = [
            "python3",
            _quote(self.remote_launcher),
            _quote(remote_env),
            _quote(self.remote_dsh_bin),
            "--profile",
            _quote(profile),
            "--patch",
            _quote(self._profile_patch(profile)),
            "--json",
        ]
        if request.resume_session_id:
            parts.extend(["--session-id", _quote(request.resume_session_id)])
        parts.append("-")
        inner = " ".join(parts)
        return f"cd {_quote(self.remote_dsh_root)} && exec {inner}"

    def _profile_for(self, request: AgentRunRequest) -> str:
        return (request.profile_name or self.profile_name).strip() or self.profile_name

    # -------------------------------------------------------------- transfer --
    def _ensure_remote_dir(self, directory: str) -> None:
        rc, out = rs._ssh(
            self.config, f"mkdir -p {_quote(directory)}", timeout=120
        )
        if rc != 0:
            raise RuntimeError(f"cannot create remote directory {directory}: {out[-500:]}")

    def _prepare_agent_ownership(self, remote_output_dir: str) -> None:
        """Give the dropped agent user its home/tmp while keeping task roots root-owned."""
        user = str(self.config.get("agent_user") or "").strip()
        if not user:
            return
        quoted = _quote(user)
        command = (
            f"chown -R root:root {_quote(self.remote_repo)} && "
            f"chmod -R a+rX {_quote(self.remote_repo)} && "
            f"chown -R {quoted}:{quoted} {_quote(remote_output_dir)} && "
            f"chmod -R u+rwX,g+rX,o-rwx {_quote(remote_output_dir)} && "
            f"chmod 711 /root"
        )
        rc, out = rs._ssh(self.config, command, timeout=600)
        if rc != 0:
            raise RuntimeError(f"cannot prepare agent ownership: {out[-800:]}")

    def _ensure_profile(self, remote_dsh_home: str, remote_home: str, profile: str) -> None:
        """Create the profile in the attempt's DSH_HOME and link the plugins.

        Mirrors ``DshHeadlessBackend._ensure_profile``: DSH materializes a
        profile from the bundled ``headless`` default on first use, and the
        profile resolves ``@component-method/*`` from its own node_modules.
        """
        manifest = f"{remote_dsh_home}/profiles/{profile}/package.json"
        script = f"""set -e
export PATH={self.remote_node_dir}:/usr/local/bin:/usr/bin:/bin
export HOME={_quote(remote_home)}
export DSH_HOME={_quote(remote_dsh_home)}
export DSH_TELEMETRY_MODE=DISABLED
cd {_quote(self.remote_dsh_root)}
if [ ! -f {_quote(manifest)} ]; then
  {_quote(self.remote_dsh_bin)} --profile {_quote(profile)} \
    --from-default-profile headless --dump-config >/dev/null
fi
test -f {_quote(manifest)}
for folder in {_quote(self.remote_dsh_root + '/plugins')}/*/; do
  base=$(basename "$folder")
  link={_quote(remote_dsh_home)}/profiles/{_quote(profile)}/node_modules/@component-method/dsh-$base
  mkdir -p "$(dirname "$link")"
  ln -sfn "$folder" "$link"
done
"""
        rc, out = rs._ssh(self.config, script, timeout=300)
        if rc != 0:
            raise RuntimeError(f"could not initialize remote DSH profile: {out[-800:]}")

    def _pull(self, remote_dir: str, local_dir: Path) -> Tuple[int, str]:
        local_dir.mkdir(parents=True, exist_ok=True)
        cfg = self.config
        target = (
            f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
        )
        ssh_parts = ["ssh"]
        ssh_parts += [str(x) for x in (cfg.get("ssh_opts") or [])]
        if cfg.get("port"):
            ssh_parts += ["-p", str(cfg["port"])]
        cmd = [
            "rsync",
            "-a",
            "--no-compress",
            # The profile's node_modules are symlinks into the remote checkout;
            # pulling them leaves dangling links in the local evidence tree.
            "--exclude=dsh_home/profiles/*/node_modules",
            "-e",
            " ".join(ssh_parts),
            f"{target}:{remote_dir}/",
            f"{local_dir}/",
        ]
        return rs._retry(cmd, cfg, timeout=1800)

    def _kill_remote(self, marker: str) -> None:
        try:
            rs._ssh(
                self.config,
                f"pkill -f {_quote(marker)} || true",
                timeout=60,
            )
        except Exception:  # noqa: BLE001 - best effort
            pass

    def _write_trajectory(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
        profile: str,
    ) -> None:
        identity = self.runtime_identity()
        identity.update(
            {
                "profile_name": profile,
                "profile_sha256": _sha256_file(
                    self.repository_root / "dsh" / "profiles" / profile / "cordis.patch.yml"
                ),
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
                    "remote_dsh_home": "dsh_home",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ run --
    def run(
        self,
        request: AgentRunRequest,
        *,
        remote_output_dir: str,
        path_map: Sequence[Tuple[Path, str]] = (),
        method_environment: Mapping[str, str] | None = None,
    ) -> AgentRunResult:
        from component_method.agent_runtime.contracts import AgentRunResult

        request.output_dir.mkdir(parents=True, exist_ok=True)
        prompt_dir = request.output_dir / "prompt_input"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "system.txt").write_text(request.system_prompt, encoding="utf-8")
        (prompt_dir / "user.txt").write_text(request.task_prompt, encoding="utf-8")

        events_path = request.output_dir / "dsh_events.jsonl"
        current_events_path = request.output_dir / ".dsh_events.current.jsonl"
        validated_path = request.output_dir / "validated_submission.json"
        log_mode = "a" if request.resume_session_id else "w"
        validated_path.unlink(missing_ok=True)
        if not request.resume_session_id:
            events_path.unlink(missing_ok=True)
        current_events_path.unlink(missing_ok=True)

        remote_output = PurePosixPath(remote_output_dir)
        profile = self._profile_for(request)
        environment = self._environment(
            request, remote_output, path_map, method_environment or {}
        )
        _, _, _, agent_process_error, resume_error, _ = _runtime_modules()

        try:
            self.validate_runtime()
            self._ensure_remote_dir(remote_output_dir)
            self._ensure_remote_dir(str(remote_output / "agent_home"))
            self._ensure_remote_dir(str(remote_output / "tmp"))
            self._ensure_profile(
                str(remote_output / "dsh_home"),
                str(remote_output / "agent_home"),
                profile,
            )
            self._prepare_agent_ownership(str(remote_output))
            env_path = request.output_dir / "remote_env.json"
            env_path.write_text(
                json.dumps(environment, ensure_ascii=False), encoding="utf-8"
            )
            rc, out = rs._rsync_put(
                self.config, env_path, str(remote_output)
            )
            if rc != 0:
                raise RuntimeError(f"cannot ship remote environment: {out[-500:]}")
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            status = resume_error if request.resume_session_id else agent_process_error
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
            self._write_trajectory(request, result, profile)
            return result

        remote_env = str(remote_output / "remote_env.json")
        marker = remote_env
        command = self._command(profile, request, remote_env)

        return_code: int | None = None
        timed_out = False
        step_limited = False
        stdout = ""
        stderr = ""
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                rs._ssh_base(self.config) + [command],
                env=rs._ssh_env(self.config),
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
                    self._kill_remote(marker)
                    process.kill()
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    self._kill_remote(marker)
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
            stderr = f"could not launch remote DSH: {exc}"
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

        # Bring the remote agent directory back for evidence and for session
        # resume.  A failed pull must not change the verdict, so it is recorded
        # in the log only.
        pull_rc, pull_out = self._pull(remote_output_dir, request.output_dir)
        if pull_rc != 0:
            with (request.output_dir / "agent.log").open("a", encoding="utf-8") as log_file:
                log_file.write(f"[remote pull failed rc={pull_rc}] {pull_out[-800:]}\n")

        (
            _,
            _,
            parse_events,
            _,
            _,
            timeout_status,
        ) = _runtime_modules()
        result = parse_events(
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
                f"remote DSH exceeded {request.total_timeout_seconds} seconds"
                if timed_out
                else (
                    f"remote DSH reached the configured step limit of {request.step_limit}"
                    if step_limited
                    else (stderr.strip() or None)
                )
            ),
        )
        if timed_out and result.status != timeout_status:
            result = AgentRunResult(
                status=timeout_status,
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
        self._write_trajectory(request, result, profile)
        current_events_path.unlink(missing_ok=True)
        return result