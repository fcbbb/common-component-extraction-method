"""Registry and construction boundary for interchangeable agent backends."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backend import AgentBackend
from .dsh_headless import DshHeadlessBackend


@dataclass(frozen=True)
class BackendSettings:
    api_key: str
    base_url: str
    repository_root: Path | None = None
    request_timeout_ms: int = 600_000
    runtime_activation: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)


BackendBuilder = Callable[[BackendSettings], AgentBackend]


def _build_dsh(settings: BackendSettings) -> AgentBackend:
    return DshHeadlessBackend(
        api_key=settings.api_key,
        base_url=settings.base_url,
        repository_root=settings.repository_root,
        request_timeout_ms=settings.request_timeout_ms,
        runtime_activation=settings.runtime_activation,
        **dict(settings.options),
    )


_BACKEND_BUILDERS: dict[str, BackendBuilder] = {"dsh": _build_dsh}


def register_agent_backend(
    name: str,
    builder: BackendBuilder,
    *,
    replace: bool = False,
) -> None:
    normalized = name.strip().lower()
    if not normalized or not normalized.replace("_", "").replace("-", "").isalnum():
        raise ValueError("backend name must contain only letters, digits, _ or -")
    if normalized in _BACKEND_BUILDERS and not replace:
        raise ValueError(f"agent backend is already registered: {normalized}")
    _BACKEND_BUILDERS[normalized] = builder


def available_backend_names() -> tuple[str, ...]:
    return tuple(sorted(_BACKEND_BUILDERS))


def create_agent_backend(
    settings: BackendSettings,
    *,
    name: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> AgentBackend:
    from .backend import selected_backend_name

    selected = (name or selected_backend_name(environment)).strip().lower()
    try:
        builder = _BACKEND_BUILDERS[selected]
    except KeyError as exc:
        choices = ", ".join(available_backend_names())
        raise ValueError(f"unknown agent backend {selected!r}; available: {choices}") from exc
    return builder(settings)
