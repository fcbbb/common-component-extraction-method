"""Common agent protocols augmented only by the selected backend."""

import json

from component_method.component_build.workspace import COMPONENT_DIRECTORY


def extraction_prompt(request, backend):
    schema = {
        "schema": "component-drafts-v2", "status": "ready|no_component|uncertain", "reason": "",
        "components": [{"component_id": "stable-id", "status": "draft_ready", "name": "",
                        "summary": "", "type": "existing_reused_asset|cooperating_units|repeated_implementation",
                        "confidence": "medium", "members": [{"file_id": "relative/path", "unit_key": "canonical key",
                                                                "unit_id": "same canonical key", "language": backend.language_id,
                                                                "backend_id": backend.backend_id}],
                        "evidence": [{"file_id": "relative/path", "line_start": 1, "line_end": 2, "claim": ""}],
                        "artifact": {"schema": "component-artifact-v2", "language": backend.language_id,
                                     "backend_id": backend.backend_id, "files": [{"path": "relative/output/path", "role": "source"}],
                                     "entrypoints": [{"kind": "language unit kind", "qualified_name": "declared symbol",
                                                      "signature": "exact source signature", "purpose": ""}], "runtime": {}},
                        "protocol_contract": {key: "source-grounded value" for key in (
                            "capability_family", "semantic_domain", "extension_trigger", "covered_variants",
                            "downstream_guarantee", "consumers", "reuse_interface", "boundary")}}],
        "workspace_audit": {"checked_files": request.expected_files, "gaps": []},
    }
    return (
        "Extract reusable components from the read-only production repository at /testbed. "
        "Inspect the supplied source focus, its callers and dependencies. Keep extraction task-blind. "
        "workspace_audit.checked_files must include every required primary file exactly once; "
        "additional inspected repository files may be listed. "
        "Do not execute repository code or tests. Cite real source lines, preserve unit keys, and provide "
        "at least two source consumers in each eight-field protocol_contract. covered_variants is a list; "
        "consumers are objects with file_id, unit_id and role; reuse_interface contains mode "
        "(stable_entrypoint or reference_pattern) and value. For stable_entrypoint, value must exactly equal "
        "one declared entrypoint_id (or qualified_name when no explicit ID is declared), with no arguments, "
        "return type or extra module prefix. Do not supply shell commands or download dependencies. "
        "Write implementations to files and metadata to /component-output/manifest.json.\n"
        + backend.agent_instructions("extraction") + "\n"
        + "For C++ artifacts, use status draft_ready, confidence high|medium|low, "
          "and file paths rooted at include/, src/, or smoke/ (do not add a component-specific "
          "top-level directory). Include every header required by your sources or smoke files; "
          "do not reference a header that exists only in another extracted component. "
          "Template-template parameters must match the exact arity of their target: "
          "std::vector is template<class, class>, so it cannot bind to template<class> class; "
          "use a matching template parameter or an adapter. Before final submission, compile all "
          "source and smoke files with g++ -std=c++17 -I/testbed/include -I/component-output/include "
          "-I/component-output and fix every diagnostic. For smoke cases, target a non-template "
          "concrete exported function with a linkage symbol; template functions may be listed as "
          "reuse entrypoints, but add a concrete wrapper and use that wrapper in smoke cases.\n"
        + "Source focus:\n"
        + json.dumps(request.context, ensure_ascii=False, indent=2) + "\nOutput schema:\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )


def review_prompt(component, backend):
    return (
        "Independently review reusable value, source fidelity and protocol claims using the read-only "
        f"repository at /testbed and artifact files in {COMPONENT_DIRECTORY}. Do not run builds or tests. "
        "Every controlled_bash command must use cwd /testbed; use /testbed/... paths, never host paths "
        "such as /home/.../dsh. "
        "Keep confirmed_members within proposed members. Cite original source paths and line ranges. "
        "Return status confirmed, rejected or uncertain, reason, confirmed_members, evidence, artifact_review "
        "with status faithful, invalid or uncertain and reason. "
        "Report validation_dependencies as {complete: boolean, files: [repository-relative file path strings], "
        "search_scopes: [repository-relative file or directory path strings]}. Use '.' for a repository-wide "
        "search. Do not put objects, glob expressions, search patterns or explanations in either path list. "
        "Review all eight protocol fields using protocol_contract_review schema_version 2, status, reason, reviewed_fields, confirmed_fields, "
        "field_issues, field_revisions and evidence. A confirmed review has all fields confirmed and no issues. "
        "For a faithful artifact provide smoke_test {status: ready, cases: [...]}. Each case uses "
        "schema smoke-case-v2, case_id, entrypoint_id (the declared qualified name or explicit entrypoint_id), "
        "files [{path, role}], sources [{file_id, line_start, line_end, role}], expected_paths "
        "[{entrypoint_id}], and metadata (including any language/backend_id declarations and backend options). "
        "Each case must actually call its entrypoint and assert "
        "source-backed behavior; compilation or import is insufficient. For C++, the smoke entrypoint "
        "must be a non-template concrete function with a linkage symbol; use a concrete wrapper for "
        "template implementations. Write source files and "
        "manifest.json under /component-output. Do not embed code in JSON or supply build commands.\n"
        + backend.agent_instructions("review") + "\nComponent:\n" + json.dumps(component, ensure_ascii=False, indent=2)
    )
