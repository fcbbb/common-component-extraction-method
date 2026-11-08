"""Shared helpers for isolated component and task containers."""

from __future__ import annotations

from pathlib import Path

import docker


RUNTIME_SUPPORT_DIR = Path(__file__).resolve().parent
IMAGE_DIR = RUNTIME_SUPPORT_DIR / "runtime_image"
IMAGE_TAG = "component-method-repo-tools:py312"


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
