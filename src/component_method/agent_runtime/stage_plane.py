"""Where a nested stage agent executes: a container or the host itself.

The benchmark host gives every stage its own container over the Docker API.
An execution host without a Docker daemon (the rented MUSA box) cannot do
that, so the stage agent runs in the stage process's own environment instead.
``COMPONENT_DSH_STAGE_RUNTIME`` selects the plane; the method kernel forwards
it from the main agent's environment to every stage subprocess.
"""

from __future__ import annotations

import os


STAGE_RUNTIME_ENVIRONMENT = "COMPONENT_DSH_STAGE_RUNTIME"

DOCKER_STAGE_RUNTIME = "docker"
HOST_STAGE_RUNTIME = "host"

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


def stage_runtime() -> str:
    """Return the configured stage execution plane (``docker`` by default)."""
    value = (os.environ.get(STAGE_RUNTIME_ENVIRONMENT) or "").strip().lower()
    return value if value in {DOCKER_STAGE_RUNTIME, HOST_STAGE_RUNTIME} else DOCKER_STAGE_RUNTIME


def host_stage_profile(role: str) -> str:
    """Return the host-plane DSH profile for a stage role."""
    try:
        return HOST_STAGE_PROFILES[role]
    except KeyError as exc:
        raise ValueError(f"no host stage profile for role: {role}") from exc