"""Stable runtime boundary for model-driven software engineering agents."""

from .backend import AgentBackend, selected_backend_name
from .contracts import AgentRunRequest, AgentRunResult
from .dsh_headless import DshHeadlessBackend
from .factory import (
    BackendSettings,
    available_backend_names,
    create_agent_backend,
    register_agent_backend,
)

__all__ = [
    "AgentBackend",
    "AgentRunRequest",
    "AgentRunResult",
    "BackendSettings",
    "DshHeadlessBackend",
    "available_backend_names",
    "create_agent_backend",
    "register_agent_backend",
    "selected_backend_name",
]
