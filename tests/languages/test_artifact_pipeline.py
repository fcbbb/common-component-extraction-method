from copy import deepcopy
from dataclasses import replace
import json
import os

import pytest

from component_method.component_build.contracts import RepositoryContext, normalize_component_draft, validate_component_draft
from component_method.component_build.submission import load_submission
from component_method.component_build.repair.artifacts import repair_artifact_with_agent
from component_method.component_build.validation.artifact_service import validate_artifact_component
from component_method.component_build.validation.service import PROTOCOL_CONTRACT_FIELDS
from component_method.languages.contracts import ProcessResult, SmokeCase, stable_digest
from component_method.languages.registry import default_registry
from component_method.languages.task_environment import bundle_environment
from component_method.library_publish.artifacts import publish_artifact_library, select_artifact_bundle
from component_method.library_publish.agent_bundle import validate_agent_bundle
from component_method.retrieval.service import build_component_catalog
from test_real_backends import example


def fixture_component(tmp_path, language, *, call=True):
    artifact, case = example(language, call=call)
    backend = default_registry().resolve({"language": language}).single()
    repo = tmp_path / "repository"
    repo.mkdir(parents=True)
    for item in artifact.files:
        path = repo / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.content)
    members, evidence = [], []
    for item in artifact.files:
        units = backend.extract_units(item.path, item.content)
        unit = next((u for u in units if u.kind in {"function", "method"}), units[0])
        members.append({"file_id": item.path, "unit_id": unit.unit_key, "unit_key": unit.unit_key,
                        "language": language, "backend_id": backend.backend_id})
        evidence.append({"file_id": item.path, "line_start": 1, "line_end": 1,
                         "claim": "Source-backed addition contract", "role": "interface_contract"})
    case = replace(case, sources=tuple(evidence))
    component = {
        "schema": "component-draft-v2", "component_id": "addition", "status": "draft_ready",
        "name": "Addition", "summary": "Source-backed reusable addition", "type": "cooperating_units",
        "members": members, "evidence": evidence, "artifact": artifact.to_json(),
        "protocol_contract": {
            "capability_family": "addition", "semantic_domain": "integer arithmetic",
            "extension_trigger": "adding a numeric consumer", "covered_variants": ["integer values"],
            "downstream_guarantee": "sum of the supplied operands", "consumers": [
                {"file_id": m["file_id"], "unit_id": m["unit_id"], "role": "addition participant"} for m in members],
            "reuse_interface": {"mode": "stable_entrypoint", "value": case.entrypoint_id}, "boundary": "integer inputs",
        },
    }
    review = {"status": "confirmed", "reason": "Source-backed reusable operation", "confirmed_members": members,
              "evidence": evidence, "artifact_review": {"status": "faithful", "reason": "Matches source semantics"},
              "protocol_contract_review": {"schema_version": 2, "status": "confirmed", "reason": "All fields supported",
                                           "reviewed_fields": list(PROTOCOL_CONTRACT_FIELDS),
                                           "confirmed_fields": list(PROTOCOL_CONTRACT_FIELDS),
                                           "field_issues": [], "field_revisions": {}},
              "smoke_test": {"status": "ready", "cases": [case.to_json()]}}
    return component, review, RepositoryContext(repo, runtime_image=os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE", "fixture"))


def fake_executor(invocation, workspace, repository):
    report = {"executed": invocation.metadata["entrypoints"], "evidence_level": "fixture_observation"}
    return ProcessResult(0, "COMPONENT_RESULT_" + invocation.metadata["nonce"] + ":" + json.dumps(report), ""), {"image_id": "sha256:fixture"}


def test_review_object_search_scopes_do_not_block_artifact_validation(tmp_path):
    component, review, repository = fixture_component(tmp_path, "python")
    review["validation_dependencies"] = {
        "complete": True, "files": [component["members"][0]["file_id"]],
        "search_scopes": [{"scope": "/testbed", "pattern": "add"}],
    }

    class RecordedAgent:
        def run_workspace_agent(self, **kwargs):
            (kwargs["output_dir"] / "trajectory.json").write_text(json.dumps({
                "messages": [], "tool_calls": [{"input": {"command": "rg add ."}}],
            }))
            return deepcopy(review)

    result = validate_artifact_component(component_id="addition", component=component, candidate_payload={},
                                         repository=repository, agent_runner=RecordedAgent(),
                                         output_dir=tmp_path / "validation", executor=fake_executor)
    assert result["status"] == "validated", result
    dependencies = result["commonality_review"]["validation_dependencies"]
    assert dependencies["complete"] is False
    assert dependencies["search_scopes"] == ["."]
    assert review["validation_dependencies"]["complete"] is True


def test_smoke_case_normalizes_explicit_backend_identity():
    _, case = example("python")
    explicit = {**case.to_json(), "language": "python", "backend_id": "python@1"}
    loaded = SmokeCase.from_json(explicit)
    assert loaded.metadata["language"] == "python"
    assert loaded.metadata["backend_id"] == "python@1"
    assert SmokeCase.from_json(loaded.to_json()) == loaded
    explicit["metadata"] = {**explicit["metadata"], "language": "java"}
    with pytest.raises(ValueError, match="conflicting smoke case language"):
        SmokeCase.from_json(explicit)


@pytest.mark.parametrize("field, value", [("language", "java"), ("backend_id", "python@other")])
def test_smoke_case_cannot_change_artifact_backend(tmp_path, field, value):
    component, review, repository = fixture_component(tmp_path, "python")
    review["smoke_test"]["cases"][0][field] = value
    result = validate_artifact_component(component_id="addition", component=component, candidate_payload={},
                                         repository=repository, agent_runner=None, review=review,
                                         output_dir=tmp_path / "validation", executor=fake_executor)
    assert result["status"] == "failed"
    assert f"smoke case {field} does not match" in result["reason"]


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
def test_v2_submission_validation_publication_and_selection(language, tmp_path):
    component, review, repository = fixture_component(tmp_path, language)
    draft = normalize_component_draft(component, component_id="addition", origin_strategy="fixture")
    assert not validate_component_draft(draft)
    assert draft.to_json()["artifact"] == component["artifact"]
    assert "library" not in draft.to_json()
    output = tmp_path / "submission"
    output.mkdir()
    external = deepcopy(component)
    for item in external["artifact"]["files"]:
        path = output / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.pop("content"))
    (output / "manifest.json").write_text(json.dumps({"status": "ready", "components": [external]}))
    assert load_submission(output, "extraction")["components"][0] == component
    validated = validate_artifact_component(component_id="addition", component=component, candidate_payload={},
                                             repository=repository, agent_runner=None, review=review,
                                             output_dir=tmp_path / "validation", executor=fake_executor)
    assert validated["status"] == "validated", validated
    library = publish_artifact_library([{"component": component, "validation": validated}], tmp_path / "library",
                                       repository="owner/repo", source_commit="a" * 40)
    catalog = build_component_catalog(library)
    assert catalog["components"][0]["language"] == language
    selected = select_artifact_bundle(library, {"selected_bundle_ids": ["component-001"]}, tmp_path / "selected")
    validate_agent_bundle(selected, "owner/repo", "a" * 40)
    environment = bundle_environment(selected)
    assert all(str(tmp_path) not in value for value in environment.values())
    assert environment["COMPONENT_BUNDLE"] == "/testbed/component_bundle"
    manifest = json.loads((library / "manifest.json").read_text())
    validate_agent_bundle(library, "owner/repo", "a" * 40)
    broken = deepcopy(manifest)
    broken["components"][0]["file_sha256"] = {}
    (library / "manifest.json").write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="cover every"):
        validate_agent_bundle(library, "owner/repo", "a" * 40)
    (library / "manifest.json").write_text(json.dumps(manifest))
    source = library / manifest["components"][0]["files"][0]
    source.write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        select_artifact_bundle(library, {"selected_bundle_ids": ["component-001"]}, tmp_path / "tampered")
    changed = deepcopy(component)
    changed["artifact"]["files"][0]["content"] += "\n"
    with pytest.raises(ValueError, match="changed"):
        publish_artifact_library([{"component": changed, "validation": validated}], tmp_path / "invalid")


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
def test_v2_review_runtime_and_publication_in_real_container(language, tmp_path):
    if not os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE"):
        pytest.skip("set COMPONENT_MULTILANGUAGE_IMAGE for full artifact pipeline integration")
    component, review, repository = fixture_component(tmp_path, language)
    validated = validate_artifact_component(component_id="addition", component=component, candidate_payload={},
                                             repository=repository, agent_runner=None, review=review, output_dir=tmp_path / "validation")
    assert validated["status"] == "validated", validated
    assert validated["entrypoint_capabilities"][0]["validation_status"] == "validated"
    publish_artifact_library([{"component": component, "validation": validated}], tmp_path / "library")


def test_v2_review_cannot_expand_source_boundary(tmp_path):
    component, review, repository = fixture_component(tmp_path, "python")
    review["confirmed_members"] = [{"file_id": "unknown.py", "unit_key": "unknown"}]
    result = validate_artifact_component(component_id="addition", component=component, candidate_payload={},
                                         repository=repository, agent_runner=None, review=review,
                                         output_dir=tmp_path / "validation", executor=fake_executor)
    assert result["status"] == "failed"
    assert "boundary" in result["reason"]


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_selected_artifact_runs_in_original_task_image(language, tmp_path):
    task_image = os.environ.get("COMPONENT_ORIGINAL_TASK_IMAGE")
    if not task_image or not os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE"):
        pytest.skip("set both original task and validation images for cross-image handoff")
    import docker

    component, review, repository = fixture_component(tmp_path, language)
    validated = validate_artifact_component(component_id="addition", component=component, candidate_payload={},
                                             repository=repository, agent_runner=None, review=review, output_dir=tmp_path / "validation")
    assert validated["status"] == "validated", validated
    library = publish_artifact_library([{"component": component, "validation": validated}], tmp_path / "library")
    selected = select_artifact_bundle(library, {"selected_bundle_ids": ["component-001"]}, tmp_path / "selected")
    environment = bundle_environment(selected)
    if language == "python":
        script = "import common; assert common.add(20, 22) == 42; print('task-ok')"
    else:
        script = (
            "import pathlib, subprocess; "
            "pathlib.Path('/work/task.cpp').write_text('#include <adder.hpp>\\nint main() { return demo::add(20,22) == 42 ? 0 : 1; }'); "
            "subprocess.run(['g++', '/work/task.cpp', '/testbed/component_bundle/components/component-001/src/adder.cpp', '-o', '/work/task'], check=True); "
            "subprocess.run(['/work/task'], check=True); print('task-ok')"
        )
    client = docker.from_env()
    try:
        original = client.images.get(task_image)
        assert original.id != client.images.get(repository.runtime_image).id
        output = client.containers.run(original.id, ["python3", "-c", script], remove=True,
                                       network_mode="none", read_only=True, cap_drop=["ALL"],
                                       security_opt=["no-new-privileges"], pids_limit=128, mem_limit="512m",
                                       user=f"{os.getuid()}:{os.getgid()}", working_dir="/work",
                                       tmpfs={"/work": "rw,exec,mode=1777,size=32m", "/tmp": "rw,mode=1777,size=32m"}, environment=environment,
                                       volumes={str(selected): {"bind": "/testbed/component_bundle", "mode": "ro"}})
        assert output.strip() == b"task-ok"
    finally:
        client.close()


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
def test_artifact_repairs_enforce_declarations_and_line_budget(language, tmp_path):
    component, _, repository = fixture_component(tmp_path, language)
    replacement = deepcopy(component["artifact"])
    replacement["files"][0]["content"] += "\n"
    class RepairAgent:
        def run_workspace_agent(self, **kwargs):
            return {"status": "repaired", "repair_target": "artifact", "reason": "bounded fix",
                    "changes": [], "artifact": deepcopy(replacement)}
    request = {"repair_target": "artifact", "max_changed_lines": 2}
    result = repair_artifact_with_agent(RepairAgent(), repository.resolved_root(), component, request, tmp_path / "repair")
    assert result["artifact"] == replacement
    with pytest.raises(ValueError, match="changed lines"):
        repair_artifact_with_agent(RepairAgent(), repository.resolved_root(), component, {**request, "max_changed_lines": 0}, tmp_path / "budget")
    replacement["entrypoints"][0]["qualified_name"] += "Changed"
    with pytest.raises(ValueError, match="frozen declaration"):
        repair_artifact_with_agent(RepairAgent(), repository.resolved_root(), component, request, tmp_path / "declaration")
