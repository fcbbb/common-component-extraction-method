"""阶段 4 与阶段 7 共用的隔离运行环境辅助函数。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import docker

from component_method.runtime_paths import release_root


RUNTIME_SUPPORT_DIR = Path(__file__).resolve().parent
FEATUREBENCH_ROOT = RUNTIME_SUPPORT_DIR.parents[3]
IMAGE_DIR = RUNTIME_SUPPORT_DIR / "runtime_image"
IMAGE_TAG = "component-method-repo-tools:py312"
COMPONENT_AGENT_ENVIRONMENT_CLASS = (
    "component_method.task_execution.runtime_support.docker_environment."
    "ComponentAgentDockerEnvironment"
)


def _ensure_image(client: docker.DockerClient) -> tuple[str, str]:
    try:
        image = client.images.get(IMAGE_TAG)
    except docker.errors.ImageNotFound:
        built, logs = client.images.build(
            path=str(IMAGE_DIR),
            tag=IMAGE_TAG,
            rm=True,
            pull=True,
        )
        for entry in logs:
            if "error" in entry:
                raise RuntimeError(str(entry["error"]))
        image = built
    return image.id, IMAGE_TAG


def _verify_isolated_container(container: docker.models.containers.Container) -> None:
    from component_method.component_build.submission import CHECKER_PATH, OUTPUT_DIRECTORY
    from component_method.component_build.workspace import COMPONENT_DIRECTORY

    container.reload()
    attrs = container.attrs
    mounts = attrs.get("Mounts", [])
    bind_mounts = [mount for mount in mounts if mount.get("Type") == "bind"]
    other_mounts = [mount for mount in mounts if mount.get("Type") != "bind"]
    network = attrs.get("HostConfig", {}).get("NetworkMode")
    bind_destinations = [mount.get("Destination") for mount in bind_mounts]
    allowed = {"/testbed", "/root/my_repo", COMPONENT_DIRECTORY, OUTPUT_DIRECTORY, CHECKER_PATH}
    if (
        "/testbed" not in bind_destinations
        or len(bind_destinations) != len(set(bind_destinations))
        or set(bind_destinations) - allowed
    ):
        raise RuntimeError(
            "Repository containers may bind only source, supplied components, "
            "the output directory and its checker"
        )
    if any(
        mount.get("Type") != "tmpfs" or mount.get("Destination") != "/tmp"
        for mount in other_mounts
    ):
        raise RuntimeError(f"Unexpected non-repository container mounts: {other_mounts}")
    if any(
        mount.get("RW") is not (mount.get("Destination") == OUTPUT_DIRECTORY)
        for mount in bind_mounts
    ):
        raise RuntimeError("Only the designated component output bind mount may be writable")
    if network != "none":
        raise RuntimeError(f"Repository container has unexpected network mode: {network}")


def _minimal_agent_env(
    *,
    run_dir: Path,
    container_name: str,
    api_key: str,
    base_url: str,
) -> dict[str, str]:
    agent_home = run_dir / "agent_home"
    agent_home.mkdir(parents=True, exist_ok=True)
    (run_dir / "tmp").mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(agent_home),
        "XDG_CONFIG_HOME": str(agent_home / ".config"),
        "TMPDIR": str(run_dir / "tmp"),
        "PYTHONPATH": str(FEATUREBENCH_ROOT / "src"),
        "COMPONENT_METHOD_RELEASE_ROOT": str(release_root()),
        "MSWEA_CONFIGURED": "true",
        "MSWEA_API_KEY": api_key,
        "MSWEA_BASE_URL": base_url,
        "MSWEA_COST_TRACKING": "ignore_errors",
        "DEEPSEEK_API_KEY": api_key,
        "DEEPSEEK_API_BASE": base_url,
        "OPENAI_API_KEY": api_key,
        "OPENAI_API_BASE": base_url,
        "OPENAI_BASE_URL": base_url,
        "GOLDBUILD_CONTAINER_NAME": container_name,
        "PYTHONUNBUFFERED": "1",
    }
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _extract_submission(trajectory_path: Path) -> tuple[str, str, float | None, int | None]:
    if not trajectory_path.is_file():
        return "", "NoTrajectory", None, None
    try:
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", "InvalidTrajectory", None, None
    info = trajectory.get("info", {})
    stats = info.get("model_stats", {})
    submission = str(info.get("submission") or "")
    if not submission:
        for message in reversed(trajectory.get("messages", [])):
            if message.get("role") == "exit":
                submission = str(
                    message.get("extra", {}).get("submission")
                    or message.get("content")
                    or ""
                )
                break
    return (
        submission,
        str(info.get("exit_status") or "Unknown"),
        _optional_float(stats.get("instance_cost")),
        _optional_int(stats.get("api_calls")),
    )


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
