"""Language-independent review and runtime validation for artifact v2."""

from dataclasses import replace
import json
from pathlib import Path
import re

from component_method.languages.contracts import ComponentArtifact, SmokeCase, SourceUnitRef, contained_path, stable_digest
from component_method.component_build.workspace import COMPONENT_DIRECTORY
from component_method.languages.registry import default_registry
from .execution import execute_invocation


def extraction_record(component):
    return component.get("component_draft") or component.get("agent_extraction") or component.get("extraction") or component


def artifact_of(component):
    return ComponentArtifact.from_json(extraction_record(component)["artifact"])


def artifact_backend(artifact, repository=None, registry=None):
    config = {"language": artifact.language}
    if repository is not None:
        options = next((row for row in repository.metadata.get("languages", [])
                        if row["id"] == artifact.language), None)
        if options:
            config = {"languages": [options]}
    backend = (registry or default_registry()).resolve(config).single()
    if backend.backend_id != artifact.backend_id:
        raise ValueError("artifact backend version is not installed")
    if repository is not None and hasattr(backend, "set_repository"):
        backend.set_repository(repository.resolved_root())
    return backend


def _artifact_citation_content(citation, artifact):
    """Resolve a citation that refers to the mounted component bundle."""
    if artifact is None:
        return None
    file_id = citation.get("file_id")
    if not isinstance(file_id, str):
        return None
    prefixes = (
        COMPONENT_DIRECTORY + "/",
        COMPONENT_DIRECTORY.lstrip("/") + "/",
        COMPONENT_DIRECTORY.rsplit("/", 1)[-1] + "/",
    )
    relative = None
    for prefix in prefixes:
        if file_id.startswith(prefix):
            relative = file_id[len(prefix):]
            break
    if relative is None:
        return None
    for item in artifact.files:
        if item.path == relative:
            return item.content
    return None


def check_citations(values, repository, artifact=None):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("source citations are required")
    for citation in values:
        if not isinstance(citation, dict):
            raise ValueError("source citations must be objects")
        content = _artifact_citation_content(citation, artifact)
        if content is None:
            path = contained_path(repository, citation["file_id"])
            content = path.read_text() if path.is_file() else None
        start, end = citation.get("line_start"), citation.get("line_end")
        if (type(start) is not int or type(end) is not int or start < 1 or end < start
                or content is None or end > len(content.splitlines())):
            raise ValueError("source citation is missing or out of bounds")


def review_artifact_with_agent(agent_runner, repo_root, component, output_dir):
    from component_method.languages.prompts import review_prompt

    artifact = artifact_of(component)
    backend = artifact_backend(artifact)
    workspace = output_dir / "component_workspace"
    backend.materialize_component(artifact, workspace)
    (output_dir / "component.json").write_text(json.dumps(component, ensure_ascii=False, indent=2))
    result = agent_runner.run_workspace_agent(
        workspace_root=repo_root, task=review_prompt(component, backend), output_dir=output_dir,
        task_label="component-review-and-smoke", agent_role="review", component_workspace=workspace,
    )
    if result.get("status") not in {"confirmed", "rejected", "uncertain"}:
        raise ValueError("component review returned an invalid status")
    if not isinstance(result.get("reason"), str) or not result["reason"].strip():
        raise ValueError("component review must explain its decision")
    from component_method.component_build.cache.review import merge_review_dependencies, observed_dependencies

    observed = observed_dependencies(output_dir / "trajectory.json", repo_root)
    manifest = result.get("validation_dependencies")
    if isinstance(manifest, dict):
        result["validation_dependencies"] = merge_review_dependencies(manifest, observed)
    (output_dir / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def validate_artifact_component(*, component_id, component, candidate_payload, repository,
                                agent_runner, output_dir, runtime_timeout=60, review=None,
                                registry=None, executor=execute_invocation, **unused):
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"schema": "component-validation-v2", "component_id": component_id,
              "status": "unverified", "case_results": {}, "entrypoint_capabilities": []}
    try:
        from .service import _validate_protocol_contract_shape, _validate_protocol_contract_review

        record = extraction_record(component)
        artifact = artifact_of(component)
        backend = artifact_backend(artifact, repository, registry)
        identity = backend.identity().to_json()
        result.update(language=artifact.language, backend_id=artifact.backend_id,
                      backend_identity=identity, artifact_sha256=stable_digest(artifact.to_json()))
        diagnostics = backend.validate_artifact(artifact)
        if diagnostics:
            raise ValueError("; ".join(d.message for d in diagnostics))
        if any(m.get("language") != artifact.language or m.get("backend_id") != artifact.backend_id
               for m in record.get("members", [])):
            raise ValueError("source members must preserve their language and backend identity")
        members = [SourceUnitRef(artifact.language, artifact.backend_id, m["file_id"],
                                 m.get("unit_key", m.get("unit_id", ""))) for m in record.get("members", [])]
        diagnostics = backend.validate_grounding(artifact, repository.resolved_root(), members)
        if diagnostics:
            raise ValueError("; ".join(d.message for d in diagnostics))
        check_citations(record.get("evidence"), repository.resolved_root())
        entries = [{"name": e.entrypoint_id, "kind": e.kind} for e in artifact.entrypoints]
        contract = record.get("protocol_contract", component.get("protocol_contract"))
        _validate_protocol_contract_shape(contract, repository.resolved_root(), entries, label="protocol_contract")
        consumers = [SourceUnitRef(artifact.language, artifact.backend_id, m["file_id"], m["unit_id"])
                     for m in contract["consumers"]]
        diagnostics = backend.validate_grounding(artifact, repository.resolved_root(), consumers)
        if diagnostics:
            raise ValueError("protocol consumer has no corresponding source unit")
        if review is None:
            review = review_artifact_with_agent(agent_runner, repository.resolved_root(), component,
                                               output_dir / "review")
        result.update(commonality_review=review, artifact_review=review.get("artifact_review"))
        if review.get("status") != "confirmed":
            result.update(status="rejected" if review.get("status") == "rejected" else "unverified",
                          reason=review.get("reason", "reusability is not confirmed"))
            return result
        if review.get("artifact_review", {}).get("status") != "faithful":
            raise ValueError("artifact fidelity is not established")
        check_citations(review.get("evidence"), repository.resolved_root(), artifact)
        allowed = {(m.file_id, m.unit_key) for m in members}
        allowed_by_file = {}
        for file_id, unit_key in allowed:
            allowed_by_file.setdefault(file_id, set()).add(unit_key)
        confirmed = set()
        for member in review.get("confirmed_members", []):
            file_id = member.get("file_id") if isinstance(member, dict) else None
            if not isinstance(file_id, str):
                raise ValueError("review members exceed the proposed source boundary")
            candidates = allowed_by_file.get(file_id, set())
            matched = None
            for field in ("unit_key", "unit_id"):
                value = member.get(field)
                if value in candidates:
                    matched = value
                    break
                if isinstance(value, str):
                    matches = sorted(
                        candidate for candidate in candidates
                        if candidate.startswith(value)
                    )
                    if len(matches) == 1:
                        matched = matches[0]
                        break
            if matched is None:
                raise ValueError("review members exceed the proposed source boundary")
            confirmed.add((file_id, matched))
        if not confirmed or not confirmed <= allowed:
            raise ValueError("review members exceed the proposed source boundary")
        _validate_protocol_contract_review(
            review, contract, repository.resolved_root(), entries,
            artifact_files={item.path: item.content for item in artifact.files},
        )
        if review["protocol_contract_review"]["status"] not in {"confirmed", "confirmed_with_warnings"}:
            raise ValueError("protocol review blocks publication")
        plan = review.get("smoke_test", {})
        if plan.get("status") != "ready" or not plan.get("cases"):
            raise ValueError("review has no grounded smoke cases")
        seen, covered, entry_cases = set(), set(), {}
        for value in plan["cases"]:
            case = SmokeCase.from_json(value)
            for field in ("language", "backend_id"):
                if field in case.metadata and case.metadata[field] != getattr(artifact, field):
                    raise ValueError(f"smoke case {field} does not match its artifact")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", case.case_id) or case.case_id in seen:
                raise ValueError("duplicate or unsafe smoke case id")
            seen.add(case.case_id)
            check_citations(case.sources, repository.resolved_root(), artifact)
            invocation = replace(backend.prepare_smoke(artifact, case, output_dir / "cases" / case.case_id),
                                 timeout_seconds=runtime_timeout)
            process, environment = executor(invocation, output_dir / "cases" / case.case_id, repository)
            observations = backend.parse_observations(invocation, process)
            executed = {o.entrypoint_id for o in observations if o.executed}
            required = {case.entrypoint_id}
            for expected in case.expected_paths:
                if set(expected) != {"entrypoint_id"}:
                    raise ValueError("expected paths must identify declared entrypoints")
                required.add(expected["entrypoint_id"])
            passed = required <= executed and process.returncode == 0 and not process.timed_out
            if passed:
                covered.add(case.entrypoint_id)
            entry_cases.setdefault(case.entrypoint_id, []).append(passed)
            result["case_results"][case.case_id] = {
                "status": "validated" if passed else "failed", "observations": [o.to_json() for o in observations],
                "environment": environment, "process": process.to_json(),
            }
        covered = {entry for entry, passed in entry_cases.items() if all(passed)}
        result["entrypoint_capabilities"] = [
            {"entrypoint": e.entrypoint_id, "signature": e.signature,
             "validation_status": "validated" if e.entrypoint_id in covered else "unverified",
             "availability": "implemented", "case_ids": [v["case_id"] for v in plan["cases"]
                                                         if v["entrypoint_id"] == e.entrypoint_id]}
            for e in artifact.entrypoints]
        result["status"] = "validated" if covered else "failed"
        result["component_sha256"] = stable_digest(component)
        result["source_sha256"] = {m.file_id: stable_digest(contained_path(repository.repo_root, m.file_id).read_text())
                                   for m in members}
    except Exception as exc:
        result.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
    finally:
        (output_dir / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
