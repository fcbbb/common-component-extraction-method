"""MiniSWE environment that executes shell actions inside one repo-only Docker."""

from __future__ import annotations

import os
import platform
import shlex
from typing import Any

import docker
from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig

from .completion import is_completion, raise_if_completed


TOOL_ENV = {
    "HOME": "/tmp",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PAGER": "cat",
    "PYTHONDONTWRITEBYTECODE": "1",
    "TMPDIR": "/tmp",
}
TASK_OUTPUT_LIMIT = 160_000


class RepositoryDockerEnvironment(LocalEnvironment):
    """Run model-generated commands in the selected read-only repository mount."""

    output_limit: int | None = TASK_OUTPUT_LIMIT

    def __init__(
        self,
        *,
        config_class: type = LocalEnvironmentConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(config_class=config_class, **kwargs)
        name = os.environ.get("GOLDBUILD_CONTAINER_NAME", "").strip()
        if not name:
            raise RuntimeError("GOLDBUILD_CONTAINER_NAME is required")
        self.container_name = name
        self.runtime_activation = os.environ.get("COMPONENT_RUNTIME_ACTIVATION", "")
        self.client = docker.from_env()

    def execute(
        self,
        action: dict,
        cwd: str = "",
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        command = action.get("command", "")
        workdir = cwd or self.config.cwd or "/testbed"
        seconds = timeout or self.config.timeout
        activation = getattr(self, "runtime_activation", "")
        if activation:
            command = activation + " && " + command
        wrapped = f"timeout --signal=KILL {int(seconds)}s /bin/bash -lc {shlex.quote(command)}"
        try:
            container = self.client.containers.get(self.container_name)
            result = container.exec_run(
                ["/bin/bash", "-lc", wrapped],
                workdir=workdir,
                environment={
                    **TOOL_ENV,
                    **({"PYTHONPATH": "/testbed"} if activation else {}),
                    **({"COMPONENT_OUTPUT_ROLE": self.output_role} if getattr(self, "output_role", "") else {}),
                },
                user="10001:10001",
                demux=False,
                tty=False,
                privileged=False,
            )
            output = (result.output or b"").decode("utf-8", errors="replace")
            if self.output_limit is not None and len(output) > self.output_limit:
                output = (
                    output[: self.output_limit // 2]
                    + "\n[output truncated by repository environment]\n"
                    + output[-self.output_limit // 2 :]
                )
            response = {
                "output": output,
                "returncode": result.exit_code,
                "exception_info": "",
            }
        except Exception as exc:
            response = {
                "output": "",
                "returncode": -1,
                "exception_info": f"Repository container command failed: {type(exc).__name__}: {exc}",
            }
        self._check_finished(response)
        return response

    def _check_finished(self, output: dict[str, Any]) -> None:
        raise_if_completed(output)

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        uname = platform.uname()
        safe = {
            "cwd": self.config.cwd or "/testbed",
            "env": {},
            "timeout": self.config.timeout,
            "system": uname.system,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
            "task_python_environment": bool(getattr(self, "runtime_activation", "")),
        }
        safe.update(kwargs)
        return safe


class ComponentAgentDockerEnvironment(RepositoryDockerEnvironment):
    """Accept completion only after the generated files pass syntax checks."""

    output_limit = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.output_role = os.environ.get("COMPONENT_OUTPUT_ROLE", "")

    def _check_finished(self, output: dict[str, Any]) -> None:
        if is_completion(output) and getattr(self, "output_role", ""):
            from ...component_build.submission import CHECKER_PATH, OUTPUT_DIRECTORY

            command = (
                f"python {CHECKER_PATH} --role {shlex.quote(self.output_role)} "
                f"--output {OUTPUT_DIRECTORY}"
            )
            activation = getattr(self, "runtime_activation", "")
            if activation:
                command = activation + " && " + command
            try:
                result = self.client.containers.get(self.container_name).exec_run(
                    ["/bin/bash", "-lc", "timeout 120s " + "/bin/bash -lc " + shlex.quote(command)],
                    user="10001:10001", environment=TOOL_ENV,
                )
                checked = (result.output or b"").decode("utf-8", errors="replace")
                if result.exit_code != 0:
                    output.update(output=checked, returncode=1)
                    return
            except Exception as exc:
                output.update(output=f"Could not check submission files: {exc}. Correct the problem and submit again.", returncode=1)
                return
            # The trajectory stores only an acknowledgement. Actual results
            # come from the persistent files, checked again by the controller.
            output["output"] = 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n{"transport":"files"}\n'
        super()._check_finished(output)
