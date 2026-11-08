"""Historical Python extraction prompt for v1 callers."""
from __future__ import annotations
import json

def legacy_extraction_prompt(request: ExtractionRequest, system_prompt: str) -> str:
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
