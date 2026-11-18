"""Common agent protocols augmented only by the selected backend."""

import json

from component_method.component_build.workspace import COMPONENT_DIRECTORY
from component_method.languages.agent_contract import (
    extraction_output_schema,
    review_output_schema,
)


def extraction_prompt(request, backend):
    schema = extraction_output_schema(backend)
    return (
        "Extract reusable components from the read-only production repository at /testbed. "
        "Inspect the supplied source focus, its callers and dependencies. Keep extraction task-blind. "
        "workspace_audit.checked_files must include every required primary file exactly once; "
        "additional inspected repository files may be listed. "
        "Do not execute repository code or tests. Cite real source lines, preserve unit keys, and provide "
        "at least two source consumers in each eight-field protocol_contract. covered_variants is a list; "
        "consumers are objects with file_id, unit_id and role, where unit_id is a real source unit key "
        "from that file, and every consumer file_id must also appear as a citation in the component's "
        "evidence list. reuse_interface contains exactly mode "
        "(stable_entrypoint or reference_pattern) and value, with no other keys. For stable_entrypoint, "
        "value must exactly equal "
        "one declared entrypoint_id (the entrypoint's qualified_name when no explicit ID is declared), "
        "with no arguments, return type or extra module prefix. protocol_contract must contain exactly the "
        "eight fields shown in the schema and no others. Do not supply shell commands or download "
        "dependencies. Write implementations to files and metadata to /component-output/manifest.json.\n"
        + backend.agent_instructions("extraction") + "\n"
        + "For C++ artifacts, use status draft_ready, confidence high|medium|low, "
          "and file paths rooted at include/, src/, or smoke/ (do not add a component-specific "
          "top-level directory). artifact.files[].role must be exactly header, source or smoke. "
          "artifact.entrypoints[].qualified_name must name the symbol exactly as declared, including "
          "its namespace and class; signature is the exact source signature. "
          "Include every header required by your sources or smoke files; "
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
    schema = review_output_schema(backend)
    return (
        "Independently review reusable value, source fidelity and protocol claims using the read-only "
        f"repository at /testbed and artifact files in {COMPONENT_DIRECTORY}. Do not run builds or tests. "
        "Every controlled_bash command must use cwd /testbed; use /testbed/... paths, never host paths "
        "such as /home/.../dsh. "
        "Keep confirmed_members within the proposed members in component.json. Copy file_id and unit_key "
        "exactly from component.members[]. Each member entry also carries the resolved name, "
        "qualified_name and line_start/line_end of that source unit, so identify the declaration by "
        "those fields and copy its unit_key. If you cannot copy unit_key, give the member name from "
        "component.members and its line_start/line_end; the controller grounds that citation against the "
        "source units. Do not invent identifiers or cite symbols that are not proposed members. "
        "Cite original source paths and line ranges in evidence; artifact comparisons may additionally "
        "cite the component bundle. A confirmed review needs at least one confirmed member and a "
        "non-empty evidence list; each citation carries file_id, line_start, line_end and a non-empty "
        "claim. "
        "Return exactly the review object shown in the output schema, including status, reason, "
        "confirmed_members, evidence, artifact_review, protocol_contract_review, smoke_test and "
        "validation_dependencies. "
        "artifact_review.status is faithful, invalid or uncertain and needs a reason. "
        "Report validation_dependencies as {complete: boolean, files: [repository-relative file path strings], "
        "search_scopes: [repository-relative file or directory path strings]}. Use '.' for a repository-wide "
        "search. Do not put objects, glob expressions, search patterns or explanations in either path list. "
        "Review all eight protocol fields using protocol_contract_review: schema_version 2, status, reason, "
        "reviewed_fields, confirmed_fields, field_issues and field_revisions. Account for every field in "
        "either confirmed_fields or field_issues, but not both. Each field issue needs field, status, "
        "severity, issue and evidence; evidence must cite original repository sources, not only the "
        "component bundle. A confirmed review has all fields confirmed and no issues. A "
        "confirmed_with_warnings review has warning issues only. A needs_revision review has blocking "
        "issues and field_revisions containing exactly those blocking fields; rejected reviews carry no "
        "revisions. "
        "For a faithful artifact provide smoke_test {status: ready, cases: [...]}. Each case uses "
        "schema smoke-case-v2, a case_id unique within the review and matching [A-Za-z0-9_-]+, "
        "entrypoint_id (the declared qualified name or explicit entrypoint_id), "
        "files [{path, role}], sources [{file_id, line_start, line_end, role}], and "
        "expected_paths. expected_paths is a list of objects shaped exactly like "
        '{"entrypoint_id": "<declared entrypoint id>"}: the entrypoint id is the value of '
        "the entrypoint_id key, never the key itself, it must name an entrypoint declared "
        "by this artifact, and each object has no other keys. Provide metadata (including any "
        "language/backend_id declarations and backend options). "
        "Each case must actually call its entrypoint and assert "
        "source-backed behavior; compilation or import is insufficient. For C++, the smoke entrypoint "
        "must be a non-template concrete function with a linkage symbol; use a concrete wrapper for "
        "template implementations. "
        "Write smoke source files, artifact files and manifest.json under /component-output; reference "
        "smoke files by path only (no inline content). "
        "Do not embed code in JSON or supply build commands.\n"
        + backend.agent_instructions("review") + "\nComponent:\n" + json.dumps(component, ensure_ascii=False, indent=2)
        + "\nOutput schema:\n" + json.dumps(schema, ensure_ascii=False, indent=2)
    )