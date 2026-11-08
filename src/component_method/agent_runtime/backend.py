"""Agent backend interface and DSH runtime selection."""

from __future__ import annotations

import os
from typing import Mapping, Protocol

from .contracts import AgentRunRequest, AgentRunResult


AGENT_BACKEND_ENV = "AGENT_BACKEND"
DEFAULT_AGENT_BACKEND = "dsh"


class AgentBackend(Protocol):
    def validate_runtime(self) -> None:
        """Raise when the selected backend runtime is unavailable or invalid."""

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run one agent session against its pre-created task container."""

    def runtime_identity(self) -> dict[str, str | None]:
        """Return fields that distinguish cache and audit identities."""


def selected_backend_name(environment: Mapping[str, str] | None = None) -> str:
    from .factory import available_backend_names

    source = os.environ if environment is None else environment
    name = source.get(AGENT_BACKEND_ENV, DEFAULT_AGENT_BACKEND).strip().lower()
    supported = available_backend_names()
    if name not in supported:
        choices = ", ".join(supported)
        raise ValueError(f"{AGENT_BACKEND_ENV} must be one of: {choices}")
    return name
