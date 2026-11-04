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
    if request.workspace_scope == "repository":
        scope_text = (
            "Explore the production source files available in the read-only workspace. "
            "Inspect related files and dependencies before deciding what to extract."
        )
    elif request.workspace_scope == "candidate":
        scope_text = (
            "The complete repository is visible in the read-only workspace. Focus extraction "
            "on the listed primary source files and units, and inspect related repository code "
            "when needed to understand their contracts and boundaries."
        )
    else:
        scope_text = (
            "Explore the files in the read-only workspace mounted at /testbed. "
            "Discover and inspect the source files yourself. Do not claim to inspect files "
            "outside this workspace."
        )
    if request.context.get("repository_context_available"):
        scope_text += (
            " The full task repository is visible for dependency inspection and imports. "
            "Extract from the required primary files; other files provide repository context."
        )
    output_schema = {
        "schema": "component-drafts-v1",
        "status": "ready|no_component|uncertain",
        "reason": "",
        "components": [
            {
                "component_id": "stable id",
                "status": "draft_ready|not_extractable",
                "name": "",
                "summary": "",
                "type": "existing_reused_asset|cooperating_units|repeated_implementation",
                "confidence": "high|medium|low",
                "relationships": [],
                "invariants": [],
                "variation_points": [],
                "members": [{"file_id": "relative/path.py", "unit_id": ""}],
                "evidence": [
                    {"file_id": "relative/path.py", "line_start": 1, "line_end": 2, "claim": ""}
                ],
                "library": {"path": "components/stable-id/common.py"},
                "entrypoints": [{"name": "", "kind": "function|class", "purpose": ""}],
                "dependencies": [],
                "limitations": [],
                "guidance": {},
                "applicability": {"conditions": [], "non_applicability": []},
                "integration_steps": [],
            }
        ],
    }
    if request.output_contract:
        fields = set(request.output_contract.get("required_fields", [])) | set(
            request.output_contract.get("optional_fields", [])
        )
        output_schema["components"][0] = {
            key: value for key, value in output_schema["components"][0].items() if key in fields
        }
    if request.workspace_scope == "repository" or request.expected_files:
        output_schema["workspace_audit"] = {"checked_files": [], "gaps": []}
    return (
        system_prompt.strip()
        + "\n\nWorkspace rule: " + scope_text
        + "\n\nDiscovery strategy: " + request.strategy
        + "\n\nExtraction context:\n"
        + json.dumps(request.context, ensure_ascii=False, indent=2)
        + "\n\nWrite manifest.json in /component-output matching this schema."
        + " Evidence must cite real lines in the visible workspace.\n"
        + "Required component fields: " + json.dumps(request.output_contract.get("required_fields", []), ensure_ascii=False) + "\n"
        + "Entrypoints must be top-level functions or classes.\n"
        + json.dumps(output_schema, ensure_ascii=False, indent=2)
        + ("\nFor scoped output, cite file_id as the complete POSIX path relative to the "
           "mounted /testbed workspace root; include every directory component exactly as "
           "visible there. Do not shorten paths relative to a package subdirectory. Use unit_id "
           "exactly as one of: module, function:<name>, class:<name>, or "
           "method:<Class>.<method>. Module-level code uses exactly module, without a module "
           "name suffix. Each entrypoint name must be one unqualified Python identifier; put any "
           "qualifying context in purpose. Discover symbols by exploring /testbed; the listed primary "
           "paths and units define the extraction focus for this batch.\n"
           if request.workspace_scope in {"community", "candidate"} else "")
        + ("\nFor workspace audit, list every required primary file exactly once in checked_files: "
           + json.dumps(request.expected_files, ensure_ascii=False)
           + ". Do not list boundary files as checked primary files. Report unreadable files in gaps."
           if request.expected_files else "")
        + "\nWrite each component's code as a separate .py file; library.path is relative to /component-output."
        + "\nIf no component is justified, write status no_component and an empty components list."
    )


def normalize_extraction_result(
    response: dict[str, Any],
    *,
    strategy: str,
    output_dir: Path,
    workspace_root: Path,
    expected_files: list[str] | None = None,
    required_fields: list[str] | None = None,
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
    )
    return drafts
