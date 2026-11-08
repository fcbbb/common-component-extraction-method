"""Invoke a repository-capable agent to discover reusable source capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import ComponentDraft, normalize_component_draft, validate_component_draft


@dataclass(frozen=True)
class ExtractionRequest:
    workspace_root: Path
    output_dir: Path
    strategy: str
    workspace_scope: str = "repository"
    context: dict[str, Any] = field(default_factory=dict)
    expected_files: list[str] = field(default_factory=list)
    output_contract: dict[str, list[str]] = field(default_factory=dict)


def _task_prompt(request: ExtractionRequest, system_prompt: str) -> str:
    if request.context.get("language"):
        from component_method.languages.prompts import extraction_prompt
        from component_method.languages.registry import default_registry

        backend = default_registry().resolve({"language": request.context["language"]}).single()
        return extraction_prompt(request, backend)
    from component_method.languages.python.prompts import legacy_extraction_prompt

    return legacy_extraction_prompt(request, system_prompt)


def normalize_extraction_result(
    response: dict[str, Any],
    *,
    strategy: str,
    output_dir: Path,
    workspace_root: Path,
    expected_files: list[str] | None = None,
    required_fields: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> list[ComponentDraft]:
    if not isinstance(response, dict):
        raise ValueError("extraction agent response must be a JSON object")
    status = response.get("status")
    if status not in {"ready", "no_component", "uncertain"}:
        raise ValueError(f"unsupported extraction response status: {status!r}")
    components = response.get("components", [])
    workspace_audit = response.get("workspace_audit", {})
    if not isinstance(workspace_audit, dict):
        raise ValueError("extraction workspace_audit must be an object")
    checked_files = workspace_audit.get("checked_files", [])
    gaps = workspace_audit.get("gaps", [])
    if not isinstance(checked_files, list) or not all(isinstance(item, str) for item in checked_files):
        raise ValueError("workspace_audit.checked_files must be a list of paths")
    if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
        raise ValueError("workspace_audit.gaps must be a list of strings")
    if expected_files is not None and (
        len(checked_files) != len(set(checked_files)) or set(checked_files) != set(expected_files)
    ):
        raise ValueError("extraction agent did not report every expected primary file exactly once")
    if not isinstance(components, list):
        raise ValueError("extraction agent components must be a list")

    drafts: list[ComponentDraft] = []
    errors: list[dict[str, Any]] = []
    seen_component_ids: set[str] = set()
    for index, value in enumerate(components):
        if not isinstance(value, dict):
            errors.append({"index": index, "errors": ["component must be an object"]})
            continue
        component_id = str(value.get("component_id") or f"{strategy}-{index + 1:03d}")
        if component_id in seen_component_ids:
            errors.append({"component_id": component_id, "errors": ["component_id must be unique in the response"]})
            continue
        seen_component_ids.add(component_id)
        draft = normalize_component_draft(
            value,
            component_id=component_id,
            origin_strategy=strategy,
        )
        draft_errors = validate_component_draft(draft)
        if context and context.get("language") and draft.status == "draft_ready":
            if (draft.artifact is None or draft.artifact.language != context["language"]
                    or draft.artifact.backend_id != context["backend_id"]):
                draft_errors.append("extraction changed the packet backend")
            focus = {(u["file_id"], u.get("unit_key", u.get("unit_id")))
                     for u in context.get("primary_extraction_units", [])}
            members = {(m["file_id"], m.get("unit_key", m.get("unit_id"))) for m in draft.members}
            if focus and not members & focus:
                draft_errors.append("extracted component has no exact focus member")
        missing_required = sorted(set(required_fields or []) - set(value))
        if missing_required:
            draft_errors.append(f"component is missing required fields: {missing_required}")
        root = workspace_root.resolve()
        for evidence_index, evidence in enumerate(draft.evidence):
            file_id = evidence.get("file_id")
            start, end = evidence.get("line_start"), evidence.get("line_end")
            if (
                not isinstance(file_id, str)
                or Path(file_id).is_absolute()
                or ".." in Path(file_id).parts
                or not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 1
                or end < start
            ):
                draft_errors.append(f"evidence {evidence_index} has invalid path or line bounds")
                continue
            source_path = (root / file_id).resolve()
            if root not in source_path.parents or not source_path.is_file():
                draft_errors.append(f"evidence {evidence_index} does not resolve in workspace")
                continue
            try:
                line_count = len(source_path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeError):
                draft_errors.append(f"evidence {evidence_index} source is unreadable")
                continue
            if end > line_count:
                draft_errors.append(f"evidence {evidence_index} exceeds source file line count")
        for member_index, member in enumerate(draft.members):
            file_id = member.get("file_id")
            if not isinstance(file_id, str) or Path(file_id).is_absolute() or ".." in Path(file_id).parts:
                draft_errors.append(f"member {member_index} has an invalid file path")
                continue
            member_path = (root / file_id).resolve()
            if root not in member_path.parents or not member_path.is_file():
                draft_errors.append(f"member {member_index} does not resolve in workspace")
        if draft_errors:
            errors.append({"component_id": component_id, "errors": draft_errors})
        else:
            drafts.append(draft)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "extraction_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "extraction_schema_validation.json").write_text(
        json.dumps({
            "status": "ok" if not errors else "partial" if drafts else "invalid",
            "accepted_component_ids": [draft.component_id for draft in drafts],
            "errors": errors,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if errors and not drafts:
        raise ValueError(f"extraction output failed schema validation: {errors}")
    return drafts


def extract_components(
    request: ExtractionRequest,
    *,
    agent_runner: Any,
    system_prompt: str,
) -> list[ComponentDraft]:
    """Run the common extraction interface over a caller-provided workspace.

    ``workspace_root`` encodes visibility. Task-backed regional extraction can
    expose the full task repository while expected_files defines primary scope.
    """
    workspace = request.workspace_root.expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"extraction workspace does not exist: {workspace}")
    task = _task_prompt(request, system_prompt)
    (request.output_dir / "extraction_task.txt").parent.mkdir(parents=True, exist_ok=True)
    (request.output_dir / "extraction_task.txt").write_text(task, encoding="utf-8")
    response = agent_runner.run_workspace_agent(
        workspace_root=workspace,
        task=task,
        output_dir=request.output_dir,
        task_label=f"component-extraction-{request.strategy}",
    )
    drafts = normalize_extraction_result(
        response,
        strategy=request.strategy,
        output_dir=request.output_dir,
        workspace_root=workspace,
        expected_files=request.expected_files if request.expected_files else None,
        required_fields=request.output_contract.get("required_fields"),
        context=request.context,
    )
    return drafts
