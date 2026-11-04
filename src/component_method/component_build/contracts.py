"""Stable data contracts shared by component discovery strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPOSITORY_CONTEXT_SCHEMA = "repository-context-v1"
COMPONENT_DRAFT_SCHEMA = "component-draft-v1"
VALIDATION_RESULT_SCHEMA = "component-validation-v1"


@dataclass(frozen=True)
class RepositoryContext:
    """A task repository and its matching execution environment.

    ``repo_root`` is the read-only source checkout visible to review agents.
    Runtime fields identify the same task environment used to execute smoke
    cases. A context may carry either a Docker image or an already initialized
    task container.
    """

    repo_root: Path
    repository_id: str = ""
    task_id: str = ""
    base_commit: str = ""
    runtime_image: str | None = None
    runtime_activation: str | None = None
    container_manager: Any = field(default=None, repr=False, compare=False)
    container: Any = field(default=None, repr=False, compare=False)
    container_workdir: str = "/testbed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolved_root(self) -> Path:
        root = self.repo_root.expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"repository workspace does not exist: {root}")
        if not self.runtime_image and not (self.container_manager and self.container):
            raise ValueError(
                "repository context requires the matching task container "
                "or a repository runtime image"
            )
        return root

    def to_json(self) -> dict[str, Any]:
        """Return serializable task metadata without exposing Docker handles."""
        return {
            "schema": REPOSITORY_CONTEXT_SCHEMA,
            "repository_id": self.repository_id,
            "task_id": self.task_id,
            "base_commit": self.base_commit,
            "repo_root": str(self.repo_root.expanduser().resolve()),
            "runtime": (
                {
                    "kind": "docker_image",
                    "image": self.runtime_image,
                    "activation": self.runtime_activation,
                }
                if self.runtime_image
                else {
                    "kind": "task_container",
                    "workdir": self.container_workdir,
                }
            ),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ComponentDraft:
    """Canonical extracted component record persisted before validation."""

    component_id: str
    status: str
    name: str = ""
    summary: str = ""
    component_type: str = ""
    confidence: str = "medium"
    relationships: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    variation_points: tuple[str, ...] = ()
    library_content: str = ""
    entrypoints: tuple[dict[str, Any], ...] = ()
    members: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    dependencies: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    guidance: dict[str, Any] = field(default_factory=dict)
    applicability: dict[str, list[str]] = field(default_factory=dict)
    integration_steps: tuple[str, ...] = ()
    origin_strategy: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": COMPONENT_DRAFT_SCHEMA,
            "component_id": self.component_id,
            "status": self.status,
            "name": self.name,
            "summary": self.summary,
            "type": self.component_type,
            "confidence": self.confidence,
            "relationships": list(self.relationships),
            "invariants": list(self.invariants),
            "variation_points": list(self.variation_points),
            "library": {"content": self.library_content},
            "entrypoints": list(self.entrypoints),
            "members": list(self.members),
            "evidence": list(self.evidence),
            "dependencies": list(self.dependencies),
            "limitations": list(self.limitations),
            "guidance": self.guidance,
            "applicability": self.applicability,
            "integration_steps": list(self.integration_steps),
            "origin_strategy": self.origin_strategy,
        }


def normalize_component_draft(
    value: dict[str, Any],
    *,
    component_id: str,
    origin_strategy: str,
) -> ComponentDraft:
    """Normalize the three legacy result shapes into the shared draft schema."""
    extraction = value.get("agent_extraction") or value.get("extraction") or value
    if not isinstance(extraction, dict):
        extraction = {}

    status = extraction.get("status", "missing")
    library = extraction.get("library")
    if not isinstance(library, dict):
        library = value.get("library")
    content = library.get("content", "") if isinstance(library, dict) else ""
    if not isinstance(content, str):
        content = ""

    entrypoints = extraction.get("entrypoints", value.get("entrypoints", []))
    if not isinstance(entrypoints, list):
        entrypoints = []
    members = value.get("members", [])
    evidence = value.get("evidence", [])
    dependencies = value.get("dependencies", value.get("required_dependencies", []))
    limitations = extraction.get("limitations", value.get("limitations", []))
    guidance = value.get("guidance", value.get("agent_guidance", {}))
    applicability = value.get("applicability", {})
    integration_steps = value.get("integration_steps", [])
    relationships = value.get("relationships", [])
    invariants = value.get("invariants", [])
    variation_points = value.get("variation_points", [])
    confidence = value.get("confidence", "medium")

    return ComponentDraft(
        component_id=component_id,
        status=status if isinstance(status, str) else "invalid",
        name=str(value.get("name") or value.get("candidate_id") or component_id),
        summary=str(value.get("capability") or value.get("summary") or ""),
        component_type=str(value.get("type") or value.get("candidate_kind") or ""),
        confidence=confidence if isinstance(confidence, str) else "invalid",
        relationships=tuple(item for item in relationships if isinstance(item, str)) if isinstance(relationships, list) else (),
        invariants=tuple(item for item in invariants if isinstance(item, str)) if isinstance(invariants, list) else (),
        variation_points=tuple(item for item in variation_points if isinstance(item, str)) if isinstance(variation_points, list) else (),
        library_content=content,
        entrypoints=tuple(x for x in entrypoints if isinstance(x, dict)),
        members=tuple(x for x in members if isinstance(x, dict)) if isinstance(members, list) else (),
        evidence=tuple(x for x in evidence if isinstance(x, dict)) if isinstance(evidence, list) else (),
        dependencies=tuple(x for x in dependencies if isinstance(x, str)) if isinstance(dependencies, list) else (),
        limitations=tuple(x for x in limitations if isinstance(x, str)) if isinstance(limitations, list) else (),
        guidance=guidance if isinstance(guidance, dict) else {},
        applicability=applicability if isinstance(applicability, dict) else {},
        integration_steps=(
            tuple(item for item in integration_steps if isinstance(item, str))
            if isinstance(integration_steps, list) else ()
        ),
        origin_strategy=origin_strategy,
        raw=value,
    )


def validate_component_draft(draft: ComponentDraft) -> list[str]:
    """Return schema errors for an extracted draft without executing its code."""
    errors: list[str] = []
    if draft.status == "not_extractable":
        return errors
    if draft.status != "draft_ready":
        errors.append(f"unsupported extraction status: {draft.status!r}")
    if not draft.name.strip():
        errors.append("component name is empty")
    if not draft.summary.strip():
        errors.append("component summary is empty")
    if draft.component_type not in {
        "existing_reused_asset", "cooperating_units", "repeated_implementation"
    }:
        errors.append(f"unsupported component type: {draft.component_type!r}")
    if draft.confidence not in {"high", "medium", "low"}:
        errors.append(f"invalid component confidence: {draft.confidence!r}")
    for field_name, values in (
        ("relationships", draft.relationships),
        ("invariants", draft.invariants),
        ("variation_points", draft.variation_points),
        ("dependencies", draft.dependencies),
        ("limitations", draft.limitations),
    ):
        if not all(isinstance(item, str) for item in values):
            errors.append(f"{field_name} must contain only strings")
    applicability = draft.raw.get("applicability", {})
    if not isinstance(applicability, dict) or any(
        not isinstance(key, str)
        or not isinstance(values, list)
        or not all(isinstance(value, str) for value in values)
        for key, values in applicability.items()
    ):
        errors.append("applicability must be an object containing lists of strings")
    integration_steps = draft.raw.get("integration_steps", [])
    if not isinstance(integration_steps, list) or not all(
        isinstance(item, str) for item in integration_steps
    ):
        errors.append("integration_steps must be a list of strings")
    if not draft.library_content.strip():
        errors.append("component library is empty")
    if not draft.entrypoints:
        errors.append("component has no public entrypoints")
    if not draft.members:
        errors.append("component has no source members")
    for index, member in enumerate(draft.members):
        if (
            not isinstance(member.get("file_id"), str)
            or not isinstance(member.get("unit_id"), str)
            or not member.get("unit_id", "").strip()
        ):
            errors.append(f"member {index} has invalid file_id or unit_id")
    if not draft.evidence:
        errors.append("component has no source evidence")
    for index, item in enumerate(draft.evidence):
        if (
            not isinstance(item.get("file_id"), str)
            or not isinstance(item.get("line_start"), int)
            or isinstance(item.get("line_start"), bool)
            or not isinstance(item.get("line_end"), int)
            or isinstance(item.get("line_end"), bool)
            or item.get("line_start", 0) < 1
            or item.get("line_end", 0) < item.get("line_start", 0)
            or not isinstance(item.get("claim"), str)
            or not item.get("claim", "").strip()
        ):
            errors.append(f"evidence {index} has invalid source citation or claim")
    names: list[str] = []
    for index, entrypoint in enumerate(draft.entrypoints):
        name = entrypoint.get("name")
        kind = entrypoint.get("kind")
        if not isinstance(name, str) or not name.isidentifier():
            errors.append(f"entrypoint {index} has an invalid name")
        else:
            names.append(name)
        if kind not in {"function", "class"}:
            errors.append(f"entrypoint {index} has an invalid kind")
        purpose = entrypoint.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            errors.append(f"entrypoint {index} has no purpose")
    if len(names) != len(set(names)):
        errors.append("entrypoint names must be unique")
    return errors
