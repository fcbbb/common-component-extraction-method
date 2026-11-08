"""Constrained multi-file artifact repairs, followed by a fresh review."""

from copy import deepcopy
import difflib
import json

from component_method.component_build.validation.artifact_service import artifact_backend, artifact_of, extraction_record
from component_method.languages.contracts import ComponentArtifact


def repair_artifact_with_agent(agent_runner, repo_root, component, repair_request, output_dir):
    artifact = artifact_of(component)
    backend = artifact_backend(artifact)
    target = repair_request.get("repair_target")
    if target not in {"artifact", "smoke_failure", "protocol_contract", "component_evidence", "review_manifest"}:
        raise ValueError("unknown repair target")
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = output_dir / "component_workspace"
    backend.materialize_component(artifact, workspace)
    (output_dir / "component.json").write_text(json.dumps(component, ensure_ascii=False, indent=2))
    (output_dir / "repair_request.json").write_text(json.dumps(repair_request, ensure_ascii=False, indent=2))
    prompt = (
        "Repair only the requested defects in this already-reviewed component. Keep the original repository "
        "read-only, source members, identity, language and declared entrypoints fixed. Do not claim approval. "
        "Write manifest.json with status repaired or not_repairable, repair_target, reason and changes. "
        "For artifact or smoke_failure return a complete component-artifact-v2 with files referenced by path; "
        "preserve its file set, runtime and metadata. For protocol_contract replace only allowed_protocol_fields. "
        "For component_evidence preserve current citations and append only required_evidence_files. "
        "For review_manifest change only requested citation line ranges. Never supply commands or download dependencies.\n"
        + backend.agent_instructions("repair") + "\nComponent:\n" + json.dumps(component, ensure_ascii=False, indent=2)
        + "\nRepair request:\n" + json.dumps(repair_request, ensure_ascii=False, indent=2)
    )
    result = agent_runner.run_workspace_agent(workspace_root=repo_root, task=prompt, output_dir=output_dir,
                                              task_label="component-repair-" + target, agent_role="repair",
                                              component_workspace=workspace)
    if result.get("repair_target") != target or result.get("status") not in {"repaired", "not_repairable"}:
        raise ValueError("repair changed target or status")
    if result["status"] == "not_repairable":
        return result
    if target in {"artifact", "smoke_failure"}:
        replacement = ComponentArtifact.from_json(result["artifact"])
        old = {f.path: f for f in artifact.files}
        new = {f.path: f for f in replacement.files}
        if (replacement.language != artifact.language or replacement.backend_id != artifact.backend_id
                or replacement.entrypoints != artifact.entrypoints or replacement.runtime != artifact.runtime
                or replacement.metadata != artifact.metadata or set(old) != set(new)
                or any(old[name].role != new[name].role for name in old)):
            raise ValueError("artifact repair changed a frozen declaration")
        changed = sum(1 for name in old for line in difflib.ndiff(old[name].content.splitlines(), new[name].content.splitlines())
                      if line.startswith(("+ ", "- ")))
        if changed > int(repair_request.get("max_changed_lines", 20)):
            raise ValueError("artifact repair exceeds allowed changed lines")
        errors = backend.validate_artifact(replacement)
        if errors:
            raise ValueError("; ".join(e.message for e in errors))
    elif target == "protocol_contract":
        from ..validation.service import _validate_protocol_contract_shape

        original = component["protocol_contract"]
        replacement = result["protocol_contract"]
        allowed = set(repair_request.get("allowed_protocol_fields", []))
        if not allowed or not allowed <= set(original) or set(replacement) != set(original):
            raise ValueError("protocol repair has no valid field scope")
        if any(replacement[k] != original[k] for k in set(original) - allowed):
            raise ValueError("protocol repair changed a disallowed field")
        _validate_protocol_contract_shape(replacement, repo_root,
                                         [{"name": e.entrypoint_id} for e in artifact.entrypoints], label="repaired protocol_contract")
    elif target == "component_evidence":
        from ..validation.artifact_service import check_citations

        original = component.get("evidence", [])
        replacement = result.get("evidence", [])
        required = set(repair_request.get("required_evidence_files", []))
        if not required or replacement[:len(original)] != original:
            raise ValueError("evidence repair changed existing citations")
        if {e["file_id"] for e in replacement[len(original):]} != required:
            raise ValueError("evidence repair exceeds requested source files")
        check_citations(replacement, repo_root)
    else:
        from ..validation.artifact_service import check_citations

        original = repair_request["previous_review"]
        replacement = result["review"]
        def without_bounds(value):
            if isinstance(value, list):
                return [without_bounds(v) for v in value]
            if isinstance(value, dict):
                citation = {"file_id", "line_start", "line_end"} <= set(value)
                return {k: without_bounds(v) for k, v in value.items()
                        if not (citation and k in {"line_start", "line_end"})}
            return value
        if without_bounds(original) != without_bounds(replacement):
            raise ValueError("review repair changed substantive decisions")
        check_citations(replacement.get("evidence"), repo_root)
    (output_dir / "repair.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
