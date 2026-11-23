"""Shared helpers for isolated component and task containers."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import docker


RUNTIME_SUPPORT_DIR = Path(__file__).resolve().parent
IMAGE_DIR = RUNTIME_SUPPORT_DIR / "runtime_image"
IMAGE_TAG = "component-method-repo-tools:py312"
IMAGE_BUILD_TIMEOUT_ENVIRONMENT = "COMPONENT_DSH_IMAGE_BUILD_TIMEOUT"
DEFAULT_IMAGE_BUILD_TIMEOUT = 300.0


def _build_timeout(timeout: float | None) -> float:
    if timeout is not None:
        return max(1.0, float(timeout))
    raw = os.environ.get(IMAGE_BUILD_TIMEOUT_ENVIRONMENT, "")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_IMAGE_BUILD_TIMEOUT


def _build_image(client: docker.DockerClient, *, timeout: float) -> Any:
    """Build with a hard deadline; a pull with no usable registry must not hang."""
    outcome: dict[str, Any] = {}

    def build() -> None:
        try:
            built, logs = client.images.build(
                path=str(IMAGE_DIR),
                tag=IMAGE_TAG,
                rm=True,
                pull=True,
                timeout=int(timeout),
            )
            for entry in logs:
                if "error" in entry:
                    raise RuntimeError(str(entry["error"]))
            outcome["image"] = built
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            outcome["error"] = exc

    worker = threading.Thread(target=build, name="component-image-build", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise RuntimeError(
            f"building {IMAGE_TAG} did not finish within {timeout:.0f}s; the base "
            "image may need to be pulled first. Raise "
            f"{IMAGE_BUILD_TIMEOUT_ENVIRONMENT} to wait longer, or run with "
            "COMPONENT_DSH_STAGE_RUNTIME=host"
        )
    error = outcome.get("error")
    if error is not None:
        raise RuntimeError(f"cannot prepare {IMAGE_TAG}: {error}") from error
    return outcome["image"]


def _ensure_image(
    client: docker.DockerClient, *, timeout: float | None = None
) -> tuple[str, str]:
    try:
        image = client.images.get(IMAGE_TAG)
    except docker.errors.ImageNotFound:
        image = _build_image(client, timeout=_build_timeout(timeout))
    return image.id, IMAGE_TAG


def _image_declared_volumes(
    container: docker.models.containers.Container,
) -> set[str]:
    """Return VOLUME paths declared by the container's image.

    Docker merges the image config into the container config, so ``Config``
    usually carries ``Volumes`` directly; fall back to the image object for
    older daemons or test doubles.
    """
    config = container.attrs.get("Config")
    volumes = config.get("Volumes") if isinstance(config, dict) else None
    if not isinstance(volumes, dict):
        image = getattr(container, "image", None)
        image_attrs = getattr(image, "attrs", None)
        image_config = image_attrs.get("Config") if isinstance(image_attrs, dict) else None
        volumes = image_config.get("Volumes") if isinstance(image_config, dict) else None
    if not isinstance(volumes, dict):
        return set()
    return {path for path in volumes if isinstance(path, str) and path}


def _verify_isolated_container(container: docker.models.containers.Container) -> None:
    from component_method.component_build.submission import CHECKER_PATH, OUTPUT_DIRECTORY
    from component_method.component_build.workspace import COMPONENT_DIRECTORY

    container.reload()
    attrs = container.attrs
    mounts = attrs.get("Mounts", [])
    bind_mounts = [mount for mount in mounts if mount.get("Type") == "bind"]
    other_mounts = [mount for mount in mounts if mount.get("Type") != "bind"]
    declared_volumes = _image_declared_volumes(container)
    network = attrs.get("HostConfig", {}).get("NetworkMode")
    bind_destinations = [mount.get("Destination") for mount in bind_mounts]
    allowed = {
        "/testbed", "/root/my_repo", COMPONENT_DIRECTORY, OUTPUT_DIRECTORY, CHECKER_PATH,
        "/component-tools/language_support.py",
    }
    if (
        "/testbed" not in bind_destinations
        or len(bind_destinations) != len(set(bind_destinations))
        or set(bind_destinations) - allowed
    ):
        raise RuntimeError(
            "Repository containers may bind only source, supplied components, "
            "the output directory, its checker and language support"
        )
    if any(
        mount.get("Type") != "tmpfs"
        or not (
            mount.get("Destination") == "/tmp"
            or (
                isinstance(mount.get("Destination"), str)
                and mount["Destination"].startswith("/testbed/")
                and mount["Destination"] in declared_volumes
            )
        )
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
