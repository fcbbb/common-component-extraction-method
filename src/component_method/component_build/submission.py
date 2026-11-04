"""File submission checks shared by agents and the controller (stdlib only)."""

from __future__ import annotations

import argparse
import ast
import copy
import json
from pathlib import Path
from typing import Any


OUTPUT_DIRECTORY = "/component-output"
CHECKER_PATH = "/component-tools/check_output.py"
MANIFEST_NAME = "manifest.json"
PROTOCOL_CONTRACT_FIELDS = {
    "capability_family",
    "semantic_domain",
    "extension_trigger",
    "covered_variants",
    "downstream_guarantee",
    "consumers",
    "reuse_interface",
    "boundary",
}


def _read_file(root: Path, relative: Any, *, python: bool = True) -> str:
    if not isinstance(relative, str) or not relative:
        raise ValueError("file reference must be a non-empty relative path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"file reference must stay inside the output directory: {relative}")
    # Reject symlinks, including links in parent directories. The output may be
    # untrusted; it must never resolve into source mounts or controller files.
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"symlink file references are not allowed: {relative}")
    if not cursor.resolve().is_relative_to(root.resolve()) or not cursor.is_file():
        raise ValueError(f"output file does not exist: {relative}")
    content = cursor.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"output file is empty: {relative}")
    if python:
        if path.suffix != ".py":
            raise ValueError(f"Python output must use a .py filename: {relative}")
        compile(content, relative, "exec")
    return content


def validate_proposal_review(result: dict[str, Any]) -> None:
    """Check the review protocol locally, without executing code or calling a model."""
    decision = result.get("decision")
    if set(result) & {"prompt_updates", "bundle_config", "component_contract", "community_config", "proposal"}:
        raise ValueError("proposal reviewer must not submit or modify a proposal configuration")
    if decision not in {"accept", "revise", "reject", "select_best"}:
        raise ValueError("proposal review needs accept, revise, reject or select_best decision")
    for field in ("summary", "improvement_mechanism", "expected_outcome"):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise ValueError(f"proposal review needs non-empty {field}")
    for field in ("revision_requests", "remaining_risks"):
        values = result.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"proposal review {field} must be a list of non-empty strings")
    checks = result.get("evidence_checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("proposal review needs evidence_checks")
    for check in checks:
        if not isinstance(check, dict) or check.get("status") not in {"supported", "unsupported", "uncertain"}:
            raise ValueError("invalid proposal evidence check")
        for field in ("path", "claim", "finding"):
            if not isinstance(check.get(field), str) or not check[field].strip():
                raise ValueError(f"proposal evidence check needs {field}")
    issues = result.get("issues")
    if not isinstance(issues, list):
        raise ValueError("proposal review needs an issues list")
    for issue in issues:
        if (not isinstance(issue, dict) or issue.get("severity") not in {"blocking", "major", "minor"}
                or not isinstance(issue.get("message"), str) or not issue["message"].strip()
                or not isinstance(issue.get("evidence_paths"), list)
                or any(not isinstance(path, str) or not path.strip() for path in issue["evidence_paths"])):
            raise ValueError("invalid proposal review issue")
    if decision == "select_best":
        if result["revision_requests"] or any(issue["severity"] == "blocking" for issue in issues):
            raise ValueError("final selection cannot request another revision or choose a blocked proposal")
        if not isinstance(result.get("selected_proposal_id"), str) or not result["selected_proposal_id"].strip():
            raise ValueError("final selection needs selected_proposal_id")
        ranking = result.get("ranking")
        if not isinstance(ranking, list) or not ranking:
            raise ValueError("final selection needs a ranking")
        for entry in ranking:
            if (not isinstance(entry, dict) or not isinstance(entry.get("proposal_id"), str)
                    or not entry["proposal_id"].strip() or not isinstance(entry.get("reason"), str)
                    or not entry["reason"].strip()):
                raise ValueError("invalid final selection ranking")
    else:
        if not isinstance(result.get("proposal_id"), str) or not result["proposal_id"].strip():
            raise ValueError("proposal review needs proposal_id")
        if not isinstance(result.get("eligible_for_selection"), bool):
            raise ValueError("proposal review needs boolean eligible_for_selection")
        blocking = any(issue["severity"] == "blocking" for issue in issues)
        if blocking and result["eligible_for_selection"]:
            raise ValueError("blocking proposals cannot be eligible for selection")
        if not result["eligible_for_selection"] and not blocking:
            raise ValueError("selection ineligibility requires a documented blocking issue")
        if decision == "accept" and (blocking or not result["eligible_for_selection"]):
            raise ValueError("accepted proposals must be eligible without blocking issues")
        if decision == "accept" and result["revision_requests"]:
            raise ValueError("accepted proposals cannot require further revisions")
        if decision == "revise" and not result["revision_requests"]:
            raise ValueError("revise requires concrete revision_requests")


def validate_repair(result: dict[str, Any]) -> None:
    """Check the target-specific repair envelope before source-aware validation."""
    if result.get("status") not in {"repaired", "not_repairable"}:
        raise ValueError("repair manifest needs repaired or not_repairable status")
    target = result.get("repair_target")
    if target not in {
        "review_manifest", "protocol_contract", "component_evidence", "artifact", "smoke_failure"
    }:
        raise ValueError("repair manifest has an invalid repair_target")
    if not isinstance(result.get("reason"), str) or not result["reason"].strip():
        raise ValueError("repair manifest needs a non-empty reason")
    changes = result.get("changes")
    if not isinstance(changes, list) or any(
        not isinstance(change, str) or not change.strip() for change in changes
    ):
        raise ValueError("repair manifest changes must be a list of non-empty strings")
    if result["status"] == "not_repairable":
        if changes:
            raise ValueError("not_repairable result cannot claim applied changes")
        return
    if not changes:
        raise ValueError("repaired result must describe at least one change")
    if target == "review_manifest":
        if not isinstance(result.get("review"), dict):
            raise ValueError("review_manifest repair needs a complete review object")
    elif target == "protocol_contract":
        if not isinstance(result.get("protocol_contract"), dict):
            raise ValueError("protocol_contract repair needs a complete protocol_contract")
    elif target == "component_evidence":
        evidence = result.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("component_evidence repair needs a complete evidence list")
    else:
        library = result.get("library")
        if not isinstance(library, dict) or not isinstance(library.get("content"), str):
            raise ValueError("artifact repair needs library.path referencing repaired Python source")


def _validate_protocol_review_submission(review: Any) -> None:
    """Reject v2 protocol-review shape errors while the reviewer can still fix them."""
    if not isinstance(review, dict):
        raise ValueError("protocol_contract_review must be an object")
    if review.get("schema_version") != 2:
        return
    status = review.get("status")
    if status not in {
        "confirmed", "confirmed_with_warnings", "needs_revision", "rejected"
    }:
        raise ValueError("protocol_contract_review has an invalid status")
    reviewed = review.get("reviewed_fields")
    confirmed = review.get("confirmed_fields")
    issues = review.get("field_issues")
    revisions = review.get("field_revisions")
    for name, values in (("reviewed_fields", reviewed), ("confirmed_fields", confirmed)):
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
            or not set(values) <= PROTOCOL_CONTRACT_FIELDS
        ):
            raise ValueError(f"protocol_contract_review.{name} must contain unique protocol fields")
    if not reviewed:
        raise ValueError("protocol_contract_review.reviewed_fields cannot be empty")
    if not isinstance(issues, list) or not isinstance(revisions, dict):
        raise ValueError("protocol_contract_review issues and field_revisions are malformed")
    issue_fields: set[str] = set()
    blocking_fields: set[str] = set()
    warning_fields: set[str] = set()
    for issue in issues:
        if (
            not isinstance(issue, dict)
            or issue.get("field") not in set(reviewed)
            or issue.get("status") not in {
                "overstated", "unsupported", "incomplete", "inaccurate"
            }
            or issue.get("severity") not in {"blocking", "warning"}
            or not isinstance(issue.get("issue"), str)
            or not issue["issue"].strip()
            or not isinstance(issue.get("evidence"), list)
            or not issue["evidence"]
        ):
            raise ValueError("protocol_contract_review contains a malformed field issue")
        field = issue["field"]
        issue_fields.add(field)
        (blocking_fields if issue["severity"] == "blocking" else warning_fields).add(field)
    if set(confirmed) & issue_fields or set(confirmed) | issue_fields != set(reviewed):
        raise ValueError("protocol_contract_review must account for every reviewed field once")
    if not set(revisions) <= set(reviewed):
        raise ValueError("field_revisions contains a field outside the review scope")
    if status == "confirmed" and (issues or revisions):
        raise ValueError("confirmed protocol review cannot contain issues or revisions")
    if status == "confirmed_with_warnings" and (
        not warning_fields or blocking_fields or revisions
    ):
        raise ValueError("confirmed_with_warnings requires only warning issues")
    if status == "needs_revision" and (
        not blocking_fields or set(revisions) != blocking_fields
    ):
        raise ValueError("needs_revision requires revisions for exactly the blocking fields")
    if status == "rejected" and (not blocking_fields or revisions):
        raise ValueError("rejected protocol review requires blocking issues and no revisions")


def _validate_mounted_review_citations(value: Any, source_root: Path) -> None:
    """Check review citation paths and line ranges while /testbed is still mounted."""
    if isinstance(value, list):
        for item in value:
            _validate_mounted_review_citations(item, source_root)
        return
    if not isinstance(value, dict):
        return
    if {"file_id", "line_start", "line_end"} <= set(value):
        file_id = value.get("file_id")
        start = value.get("line_start")
        end = value.get("line_end")
        if (
            not isinstance(file_id, str)
            or not file_id
            or Path(file_id).is_absolute()
            or ".." in Path(file_id).parts
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
        ):
            raise ValueError("review contains a malformed source citation")
        source_path = (source_root / file_id).resolve()
        if not source_path.is_relative_to(source_root.resolve()) or not source_path.is_file():
            raise ValueError(f"review citation does not resolve inside /testbed: {file_id}")
        line_count = len(source_path.read_text(encoding="utf-8").splitlines())
        if end > line_count:
            raise ValueError(f"review citation exceeds the end of {file_id}")
    for item in value.values():
        _validate_mounted_review_citations(item, source_root)


def load_submission(output_root: Path, role: str) -> dict[str, Any]:
    """Read and check files, then hydrate the existing internal result schema."""
    root = output_root.resolve()
    manifest = json.loads(_read_file(root, MANIFEST_NAME, python=False))
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must contain one JSON object")
    result = copy.deepcopy(manifest)

    def hydrate(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                hydrate(item)
        elif isinstance(value, dict):
            library = value.get("library")
            if isinstance(library, dict):
                if "content" in library:
                    raise ValueError("write Python source to a file and use library.path, not library.content")
                if "path" in library:
                    library["content"] = _read_file(root, library["path"])
            if "test_py" in value:
                raise ValueError("write the test to a .py file and use test_file, not test_py")
            if "test_file" in value:
                code = _read_file(root, value.pop("test_file"))
                tree = ast.parse(code)
                if not any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body):
                    raise ValueError("each smoke-test file must define run(common)")
                value["test_py"] = code
            # Only recurse through original children, avoiding the code we added.
            for key, item in list(value.items()):
                if key not in {"content", "test_py"}:
                    hydrate(item)

    hydrate(result)
    if role == "extraction":
        if ("status" in result and result["status"] not in {"ready", "no_component", "uncertain"}):
            raise ValueError("extraction manifest has an invalid status")
        components = result.get("components")
        if not isinstance(components, list):
            raise ValueError("extraction manifest must contain a components list")
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                raise ValueError(f"component {index} must be an object")
            draft = component.get("extraction", component)
            if not isinstance(draft, dict):
                raise ValueError(f"component {index} extraction must be an object")
            if draft.get("status") == "not_extractable":
                continue
            library = draft.get("library")
            if not isinstance(library, dict) or not library.get("content"):
                raise ValueError(f"component {index} needs library.path referencing its Python file")
            entrypoints = draft.get("entrypoints")
            if not isinstance(entrypoints, list) or not entrypoints:
                raise ValueError(f"component {index} needs an entrypoints list")
            for entry in entrypoints:
                if (not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
                        or not entry["name"].isidentifier() or entry.get("kind") not in {"function", "class"}):
                    raise ValueError(f"component {index} has an invalid entrypoint name or kind")
    elif role == "review":
        if result.get("status") not in {"confirmed", "rejected", "uncertain", "ready", "no_cases"}:
            raise ValueError("review manifest has an invalid status")
        capabilities = result.get("entrypoint_capabilities", [])
        if not isinstance(capabilities, list):
            raise ValueError("entrypoint_capabilities must be a list")
        for index, capability in enumerate(capabilities):
            if not isinstance(capability, dict) or any(
                not isinstance(capability.get(field), str)
                for field in ("entrypoint", "method", "contract", "example", "scope", "reason")
            ):
                raise ValueError(f"capability {index} needs string entrypoint, method, contract, example, scope and reason")
            if capability.get("availability") not in {"implemented", "missing", "unverified"}:
                raise ValueError(f"capability {index} has an invalid availability")
            if not isinstance(capability.get("case_ids", []), list) or any(
                not isinstance(case_id, str) for case_id in capability.get("case_ids", [])
            ):
                raise ValueError(f"capability {index} case_ids must be a list of strings")
        plan = result.get("smoke_test", result)
        if isinstance(plan, dict) and plan.get("status") == "ready":
            cases = plan.get("cases")
            if cases is not None:
                if not isinstance(cases, list) or not cases:
                    raise ValueError("ready smoke plan must contain non-empty cases")
                if any(not isinstance(case, dict) or not case.get("test_py") for case in cases):
                    raise ValueError("each ready case needs test_file referencing its test")
            elif not plan.get("test_py"):
                raise ValueError("ready smoke plan needs test_file or cases")
        if "protocol_contract_review" in result:
            _validate_protocol_review_submission(result["protocol_contract_review"])
        mounted_repository = Path("/testbed")
        if mounted_repository.is_dir():
            _validate_mounted_review_citations(result, mounted_repository)
    elif role == "proposal_review":
        validate_proposal_review(result)
    elif role == "repair":
        validate_repair(result)
    elif role != "proposal":
        raise ValueError(f"unknown submission role: {role}")
    return result


def file_submission_instructions() -> str:
    return (
        "\n\nFile submission protocol (applies to this run, including saved prompt templates):\n"
        f"Write the result metadata to {OUTPUT_DIRECTORY}/{MANIFEST_NAME}. "
        "Write component implementations as .py files inside that directory; "
        "library must contain path, a relative filename, instead of content. "
        "Write smoke tests as .py files and put their relative paths in test_file instead of test_py. "
        "Keep all other schema fields, source citations and entrypoint declarations. "
        "The original repository and supplied artifacts are read-only; this output directory is writable. "
        "Do not embed source code in JSON or print the manifest as the final answer. "
        f"Check your files with python {CHECKER_PATH} --role $COMPONENT_OUTPUT_ROLE "
        f"--output {OUTPUT_DIRECTORY}; this validates metadata and mounted source citations and compiles "
        "Python, without running tests. "
        "Fix errors and check again. Finish by running the same checker with --submit; "
        "it prints the completion marker only when your files are valid. "
        "The program checks the files before accepting completion; errors are returned so you can correct them."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(OUTPUT_DIRECTORY))
    parser.add_argument(
        "--role",
        choices=("extraction", "review", "repair", "proposal", "proposal_review"),
        required=True,
    )
    parser.add_argument("--submit", action="store_true", help="Check files, then print the completion marker on success")
    args = parser.parse_args()
    try:
        load_submission(args.output, args.role)
    except (ValueError, OSError, SyntaxError) as exc:
        print(f"Submission check failed: {exc}. Fix the files and check again.")
        return 1
    print("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" if args.submit else "Submission files and Python syntax are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
