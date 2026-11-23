"""Where a nested stage agent executes: a container or the host itself.

The benchmark host gives every stage its own container over the Docker API.
An execution host without a usable Docker API (a rented MUSA box, or a machine
where the Python ``docker`` package is not installed) cannot do that, so the
stage agent runs in the stage process's own environment instead.

``COMPONENT_DSH_STAGE_RUNTIME`` selects the plane; the method kernel forwards
it from the main agent's environment to every stage subprocess.  An unset or
``auto`` value probes the local Docker API: a reachable daemon whose runtime
image is present (or can be built within
``COMPONENT_DSH_IMAGE_BUILD_TIMEOUT``, default 300s) selects ``docker``,
anything else selects ``host``.  An explicit ``docker`` still builds the image
on demand with the same deadline and reports the failure.  The choice and its
reason are written to each stage's run metadata, so a run never silently
changes planes.
"""

from __future__ import annotations

import os
from functools import lru_cache


STAGE_RUNTIME_ENVIRONMENT = "COMPONENT_DSH_STAGE_RUNTIME"

DOCKER_STAGE_RUNTIME = "docker"
HOST_STAGE_RUNTIME = "host"
AUTO_STAGE_RUNTIME = "auto"

# Host-plane DSH profiles: the same stage prompt and submission contract with
# the stock `bash` tool in place of `controlled_bash`.
HOST_STAGE_PROFILES = {
    "extraction": "component-method-extraction-host",
    "review": "component-method-extraction-host",
    "repair": "component-method-extraction-host",
    "proposal": "component-method-extraction-host",
    "proposal_review": "component-method-extraction-host",
    "retrieval": "component-method-retrieval-host",
}


@lru_cache(maxsize=1)
def _docker_plane_status() -> tuple[bool, str]:
    """Probe the local Docker API once; report whether the docker plane can run."""
    try:
        import docker
    except Exception as exc:  # noqa: BLE001 - a missing package is a normal fallback
        detail = f"No module named 'docker'" if isinstance(exc, ImportError) else str(exc)
        return False, f"python docker package unavailable ({detail})"
    try:
        client = docker.from_env(timeout=2)
    except Exception as exc:  # noqa: BLE001 - unreachable daemon is a normal fallback
        return False, f"docker client unavailable ({type(exc).__name__}: {exc})"
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - unreachable daemon is a normal fallback
        return False, f"docker daemon unreachable ({type(exc).__name__}: {exc})"
    try:
        # A daemon without the runtime image cannot run the stage; prepare it
        # under a deadline instead of discovering that after the run starts.
        from component_method.task_execution.runtime_support.build_helpers import (
            _ensure_image,
        )

        _ensure_image(client)
    except Exception as exc:  # noqa: BLE001 - an unprepared image is a normal fallback
        return False, f"docker runtime image not ready ({exc})"
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
    return True, "docker daemon reachable and runtime image ready"


@lru_cache(maxsize=8)
def _resolve(raw: str) -> tuple[str, str]:
    value = raw.strip().lower()
    if value in {DOCKER_STAGE_RUNTIME, HOST_STAGE_RUNTIME}:
        return value, "explicit"
    ok, detail = _docker_plane_status()
    if value and value != AUTO_STAGE_RUNTIME:
        detail = f"unrecognised value {value!r}; {detail}"
    return (DOCKER_STAGE_RUNTIME if ok else HOST_STAGE_RUNTIME), f"auto: {detail}"


def stage_runtime() -> str:
    """Return the stage execution plane, probing Docker for ``auto``/unset."""
    return _resolve(os.environ.get(STAGE_RUNTIME_ENVIRONMENT) or "")[0]


def stage_runtime_reason() -> str:
    """Explain why :func:`stage_runtime` returned its plane."""
    return _resolve(os.environ.get(STAGE_RUNTIME_ENVIRONMENT) or "")[1]


def describe_stage_runtime() -> str:
    """One line for preflight output: the plane and the reason."""
    plane, reason = _resolve(os.environ.get(STAGE_RUNTIME_ENVIRONMENT) or "")
    return f"{plane} ({reason})"


def host_stage_profile(role: str) -> str:
    """Return the host-plane DSH profile for a stage role."""
    try:
        return HOST_STAGE_PROFILES[role]
    except KeyError as exc:
        raise ValueError(f"no host stage profile for role: {role}") from exc