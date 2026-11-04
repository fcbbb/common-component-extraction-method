"""Path coverage, complete component directories and cross-snapshot review reuse."""

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest

from component_method.component_build.contracts import RepositoryContext
from component_method.component_build.validation.service import validate_component, _case_exercises_path
from component_method.library_publish.agent_bundle import publish_agent_bundle, agent_bundle_prompt, validate_agent_bundle
from component_method.component_build.cache.review import cached_review, observed_dependencies


def test_artifact_reads_are_cached_by_review_input_and_original_sources(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text("def value(): return 1\n")
    payload = {"candidate": {"members": [{"file_id": "module.py", "unit_id": "function:value"}],
                              "entrypoints": [{"name": "value", "kind": "function"}],
                              "library": {"content": "def value(): return 1\n"}}}
    review = {"status": "confirmed", "validation_dependencies": {
        "complete": True, "files": ["module.py", ".components/common.py"], "search_scopes": [],
    }}
    calls = []

    def operation():
        calls.append(True)
        return deepcopy(review)

    runner = SimpleNamespace(model="fixture", base_url="fixture")
    cache = tmp_path / "cache"
    assert cached_review(cache, repo, payload, runner, None, operation)[1]["status"] == "miss"
    assert cached_review(cache, repo, payload, runner, None, operation)[1]["status"] == "hit"
    changed = deepcopy(payload)
    changed["candidate"]["library"]["content"] = "def value(): return 2\n"
    assert cached_review(cache, repo, changed, runner, None, operation)[1]["status"] == "miss"
    assert len(calls) == 2
    trace = tmp_path / "trajectory.json"
    trace.write_text(json.dumps({"messages": [{"role": "assistant", "extra": {"actions": [{
        "command": "cat /testbed/.components/common.py && cat /testbed/module.py",
    }]}}]}))
    assert observed_dependencies(trace, repo) == {"files": ["module.py"], "search_scopes": []}


@pytest.fixture(autouse=True)
def isolated_host_smoke(monkeypatch):
    from component_method.component_build.validation import service
    from component_method.component_build.validation.runtime import validate_callable_artifact

    def run(**kwargs):
        kwargs["runtime_image"] = None
        return validate_callable_artifact(**kwargs)
    monkeypatch.setattr(service, "validate_callable_artifact", run)


def partial_component(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    code = "class Transform:\n    def identity(self, x):\n        return x\n    def log(self, x):\n        return missing_log(x)\n"
    (repo / "module.py").write_text(code)
    member = {"file_id": "module.py", "unit_id": "class:Transform"}
    component = {"status": "draft_ready", "members": [member], "library": {"content": code},
                 "entrypoints": [{"name": "Transform", "kind": "class", "purpose": "Coordinate transformations"}]}
    citation = {"file_id": "module.py", "line_start": 1, "line_end": 5, "role": "interface_contract"}
    review = {"status": "confirmed", "reason": "Usable identity contract", "confirmed_members": [member],
              "evidence": [{**citation, "claim": "Implements identity transformation"}], "limitations": [],
              "artifact_review": {"status": "faithful", "reason": "Exact copy including missing source path"},
              "entrypoint_capabilities": [
                  {"entrypoint": "Transform", "path": f"Transform.{path}", "availability": availability,
                   "contract": f"{path} transformation", "example": f"Transform().{path}(3)", "scope": "numeric inputs",
                   "reason": "", "case_ids": case_ids}
                  for path, availability, case_ids in [("identity", "implemented", ["identity"]),
                                                       ("log", "implemented", ["log"]), ("sqrt", "missing", [])]
              ],
              "smoke_test": {"status": "ready", "cases": [
                  {"case_id": path, "entrypoint": "Transform", "sources": [citation],
                   "test_py": f"def run(common):\n    assert common.Transform().{path}(3) == 3\n    return True\n"}
                  for path in ["identity", "log"]
              ]}}
    return repo, component, review


def test_independent_cases_keep_good_path_and_mark_failed_missing_paths(tmp_path):
    repo, component, review = partial_component(tmp_path)
    result = validate_component(component_id="transform", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"), agent_runner=None,
                                output_dir=tmp_path / "validated-output", review=review)
    assert result["status"] == "validated", result
    assert {cap["path"]: cap["validation_status"] for cap in result["entrypoint_capabilities"]} == {
        "Transform.identity": "validated", "Transform.log": "failed", "Transform.sqrt": "missing"}
    assert (tmp_path / "validated-output/validated/common.py").read_text() == component["library"]["content"]


def test_constructing_class_does_not_verify_its_methods_or_other_input_modes():
    assert not _case_exercises_path("def run(common):\n    common.Transform()\n", "Transform", "Transform.log")
    assert _case_exercises_path("def run(common):\n    obj = common.Transform()\n    obj.log(3)\n", "Transform", "Transform.log")
    assert not _case_exercises_path("def run(common):\n    common.scale(mode='identity')\n", "scale", "scale(mode='log')")
    assert _case_exercises_path("def run(common):\n    common.scale(mode='log')\n", "scale", "scale(mode='log')")


@pytest.mark.parametrize("setup,call,path", [
    ("mode = 'log'", "common.scale(mode=mode)", "scale(mode='log')"),
    ("mode: str = 'log'", "common.scale(mode=mode)", "scale(mode='log')"),
    ("mode = 'log'\n    selected = mode", "common.scale(mode=selected)", "scale(mode='log')"),
    ("mode = 'identity'\n    mode = 'log'", "common.scale(mode=mode)", "scale(mode='log')"),
    ("mode = 'log'", "common.scale(mode)", "scale('log')"),
    ("limit = -3", "common.scale(limit=limit)", "scale(limit=-3)"),
])
def test_capability_modes_accept_known_scalar_variables(setup, call, path):
    source = f"def run(common):\n    {setup}\n    {call}\n    return True\n"
    assert _case_exercises_path(source, "scale", path)


@pytest.mark.parametrize("body", [
    "mode = 'log'\n    mode = 'identity'\n    common.scale(mode=mode)",
    "mode = 'identity'\n    common.scale(mode=mode)\n    mode = 'log'",
    "mode = 'log'\n    mode = common.get_mode()\n    common.scale(mode=mode)",
    "mode = 'log'\n    if common.condition():\n        mode = 'identity'\n    common.scale(mode=mode)",
    "mode = 'log'\n    mode += '-other'\n    common.scale(mode=mode)",
    "mode = 'log'\n    del mode\n    common.scale(mode=mode)",
    "mode = 'log'\n    [common.scale(mode=mode) for mode in ['identity']]",
    "mode = 'log'\n    hidden = lambda mode: common.scale(mode=mode)",
    "mode = 'log'\n    common.scale(mode=(mode := 'identity'))",
    "mode = 'log'\n    exec(\"mode = 'identity'\")\n    common.scale(mode=mode)",
])
def test_capability_mode_analysis_rejects_wrong_or_unknown_values(body):
    assert not _case_exercises_path(f"def run(common):\n    {body}\n", "scale", "scale(mode='log')")


def test_scalar_variable_mode_runs_and_is_published_as_validated(tmp_path):
    repo, component, review = partial_component(tmp_path)
    code = "def scale(value, mode):\n    return value if mode == 'identity' else -value\n"
    (repo / "module.py").write_text(code)
    component["library"]["content"] = code
    component["members"] = [{"file_id": "module.py", "unit_id": "function:scale"}]
    component["entrypoints"] = [{"name": "scale", "kind": "function"}]
    review["confirmed_members"] = deepcopy(component["members"])
    review["entrypoint_capabilities"] = [{
        "entrypoint": "scale", "path": "scale(mode='identity')", "availability": "implemented",
        "contract": "Identity mapping", "example": "scale(3, mode='identity')", "scope": "numbers",
        "reason": "", "case_ids": ["identity"],
    }]
    review["smoke_test"]["cases"] = [{
        "case_id": "identity", "entrypoint": "scale",
        "sources": [{"file_id": "module.py", "line_start": 1, "line_end": 2, "role": "interface_contract"}],
        "test_py": "def run(common):\n    mode = 'identity'\n    assert common.scale(3, mode=mode) == 3\n    return True\n",
    }]
    review["evidence"][0]["line_end"] = 2
    result = validate_component(component_id="scale", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"), agent_runner=None,
                                output_dir=tmp_path / "output", review=review)
    assert result["status"] == "validated", result
    assert result["entrypoint_capabilities"][0]["validation_status"] == "validated"


def test_wrongly_linked_case_is_unverified_not_usable(tmp_path):
    repo, component, review = partial_component(tmp_path)
    review["smoke_test"]["cases"][0]["test_py"] = "def run(common):\n    common.Transform()\n    return True\n"
    result = validate_component(component_id="transform", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"), agent_runner=None,
                                output_dir=tmp_path / "output", review=review)
    assert result["status"] == "failed"
    assert result["entrypoint_capabilities"][0]["validation_status"] == "unverified"


@pytest.mark.parametrize("body", [
    "if False:\n        obj.log(3)",
    "log = obj.log\n    log = lambda value: value\n    assert log(3) == 3",
    "obj.log = lambda value: value\n    assert obj.log(3) == 3",
])
def test_unexecuted_or_replaced_method_cannot_publish_capability(tmp_path, body):
    repo, component, review = partial_component(tmp_path)
    review["entrypoint_capabilities"] = [review["entrypoint_capabilities"][1]]
    review["smoke_test"]["cases"] = [review["smoke_test"]["cases"][1]]
    review["smoke_test"]["cases"][0]["test_py"] = (
        f"def run(common):\n    obj = common.Transform()\n    {body}\n    return True\n")
    result = validate_component(component_id="transform", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"),
                                agent_runner=None, output_dir=tmp_path / "output", review=review)
    assert result["case_results"]["log"]["status"] == "ok", result
    assert result["entrypoint_capabilities"][0]["validation_status"] == "unverified"
    assert result["status"] == "failed"
    assert not (tmp_path / "output/validated/common.py").exists()


def test_publish_complete_short_index_and_colocated_readmes(tmp_path):
    repo, component, review = partial_component(tmp_path)
    result = validate_component(component_id="transform", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"), agent_runner=None,
                                output_dir=tmp_path / "validation", review=review)
    # Long examples must survive relocation into the README.
    example = "Transform().identity(3)\n" + "# context\n" * 50
    result["entrypoint_capabilities"][0]["example"] = example
    audit = tmp_path / "audit"
    audit.mkdir()
    code = component["library"]["content"]
    (audit / "common.py").write_text(code)
    item = {"name": "Coordinate [transform]\nhelper", "capability": "All transformations", "library": "common.py",
            "members": component["members"], "entrypoints": component["entrypoints"],
            "evidence": [{"claim": "x" * 30000}], "local_validation": {"status": "validated", "validation": result}}
    result["repository"] = {"repo_root": "/host/FeatureBench/private/repository", "runtime": {"image": "private-image"}}
    result["case_results"]["log"]["reason"] = "Traceback from /host/FeatureBench/private/runner.py"
    item["guidance"] = {"location": "/opt/featurebench/community-components"}
    # More than the previous top-5 budget, all of them must remain visible.
    (audit / "unique_validated_components.jsonl").write_text("".join(json.dumps(item) + "\n" for _ in range(7)))
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "bundle_config.json").write_text(json.dumps({"index_format": "markdown",
        "library_layout": "per_component"}))
    bundle = publish_agent_bundle(audit, tmp_path / "store", "owner/repo", "a" * 40, experiment_dir=experiment)
    index = (bundle / "INDEX.md").read_text()
    assert len(index) < 2500
    assert len([line for line in index.splitlines() if line.startswith("- ")]) == 7
    assert "components/component-007/README.md" in index
    assert r"Coordinate \[transform\] helper" in index
    assert "Transform.identity(self, x)" not in index
    for number in range(1, 8):
        directory = bundle / f"components/component-{number:03d}"
        assert (directory / "component.py").read_text() == code
        readme = (directory / "README.md").read_text()
        assert "module.py" in readme and "Transform.identity(self, x)" in readme
        assert example.rstrip() in readme
        assert "Transform.log" in readme and "Status: failed" in readme
        assert "Transform.sqrt" in readme and "Status: missing" in readme
        assert "x" * 30000 not in readme
        assert "```json" not in readme
    assert "x" * 30000 in (bundle / "audit/component-001.json").read_text()
    for path in bundle.rglob("*"):
        if path.is_file():
            content = path.read_text()
            assert "featurebench" not in content.lower()
            assert "/host/" not in content and "private-image" not in content
    published_audit = json.loads((bundle / "audit/component-001.json").read_text())
    assert "repository" not in published_audit["local_validation"]["validation"]
    assert "FeatureBench" in (audit / "unique_validated_components.jsonl").read_text()
    manifest = validate_agent_bundle(bundle, "owner/repo", "a" * 40)
    assert manifest["component_count"] == 7 and "retrieval" not in manifest
    assert not any(key.startswith("retrieval") for key in manifest["bundle_config"])
    assert not any((bundle / filename).exists() for filename in
                   ("catalog.jsonl", "search.py", "component_cards.py", "cards", "index.jsonl"))
    prompt = agent_bundle_prompt(experiment)
    assert "First read the complete" in prompt and "/INDEX.md" in prompt
    assert "/testbed/component_bundle" in prompt and "featurebench" not in prompt.lower()
    assert "Choose relevant components yourself" in prompt and "similar implementations" in prompt
    assert "retrieved" not in prompt and "search.py" not in prompt
    # The manifest cannot redirect a README outside the mounted bundle.
    manifest["components"][0]["readme"] = "../outside.md"
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe component metadata path"):
        validate_agent_bundle(bundle, "owner/repo", "a" * 40)


def test_published_component_loads_repository_imports_from_an_unrelated_directory(tmp_path):
    from component_method.component_build.workspace import COMPONENT_DIRECTORY
    from component_method.library_publish.agent_bundle import BUNDLE_CONTAINER_PATH

    assert BUNDLE_CONTAINER_PATH == COMPONENT_DIRECTORY
    repo = tmp_path / "repo"
    package = repo / "source_package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "helpers.py").write_text("def clean(value): return value.strip().lower()\n")
    code = "from source_package.helpers import clean\ndef normalize(value):\n    return clean(value)\n"
    (repo / "module.py").write_text(code)
    member = {"file_id": "module.py", "unit_id": "function:normalize"}
    citation = {"file_id": "module.py", "line_start": 1, "line_end": 3, "role": "interface_contract"}
    entries = [{"name": "normalize", "kind": "function", "purpose": "Normalize strings"}]
    component = {"status": "draft_ready", "members": [member], "entrypoints": entries,
                 "library": {"content": code}}
    review = {"status": "confirmed", "reason": "Reusable normalization", "confirmed_members": [member],
              "evidence": [{**citation, "claim": "Normalizes labels"}], "limitations": [],
              "artifact_review": {"status": "faithful", "reason": "Same source behavior"},
              "entrypoint_capabilities": [{"entrypoint": "normalize", "method": "",
                  "availability": "implemented", "contract": "Normalize labels", "scope": "strings",
                  "example": "common.normalize(' A ')", "reason": "", "case_ids": ["label"]}],
              "smoke_test": {"status": "ready", "cases": [{"case_id": "label", "entrypoint": "normalize",
                  "sources": [citation], "test_py": "def run(common):\n    assert common.normalize(' A ') == 'a'\n    return True\n"}]}}
    result = validate_component(component_id="normalize", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"), agent_runner=None,
                                output_dir=tmp_path / "validation", review=review)
    assert result["status"] == "validated", result
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "common.py").write_text(code)
    item = {"name": "Normalization", "capability": "Normalize labels", "members": [member],
            "entrypoints": entries, "library": "common.py",
            "local_validation": {"status": "validated", "validation": result}}
    (audit / "unique_validated_components.jsonl").write_text(json.dumps(item) + "\n")
    bundle = publish_agent_bundle(audit, tmp_path / "store", "owner/repo", "a" * 40)
    readme = (bundle / "components/component-001/README.md").read_text()
    loading = re.search(r"```python\n(.*?)\n```", readme, re.S).group(1)
    # Map the advertised container paths to their host-side mounts.
    loading = loading.replace(COMPONENT_DIRECTORY, str(bundle)).replace("/testbed", str(repo))
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    executed = subprocess.run([sys.executable, "-I", "-c", loading + "\nassert common.normalize(' A ') == 'a'\n"
                               + f"assert common.__file__ == {str(bundle / 'components/component-001/component.py')!r}\n"],
                              cwd=unrelated, text=True, capture_output=True)
    assert executed.returncode == 0, executed.stderr
    assert (bundle / "components/component-001/component.py").read_text() == code


def test_bad_case_citation_keeps_other_verified_path(tmp_path):
    repo, component, review = partial_component(tmp_path)
    review["smoke_test"]["cases"][1]["sources"][0]["file_id"] = "../outside.py"
    # Citations were shared in the fixture; restore the good case independently.
    review["smoke_test"]["cases"][0]["sources"] = [{"file_id": "module.py", "line_start": 1, "line_end": 3, "role": "interface_contract"}]
    result = validate_component(component_id="transform", component=component, candidate_payload={},
                                repository=RepositoryContext(repo_root=repo, runtime_image="fixture"), agent_runner=None,
                                output_dir=tmp_path / "output", review=review)
    assert result["status"] == "validated", result
    assert result["entrypoint_capabilities"][1]["validation_status"] == "unverified"


def test_async_smoke_really_executes_the_assertion(tmp_path):
    from component_method.component_build.validation.runtime import validate_callable_artifact
    result = validate_callable_artifact(
        component_id="async", library_content="async def f(): return 3\n",
        smoke_content="async def run(common):\n    assert await common.f() == 4\n    return True\n",
        entrypoints=[{"name": "f", "kind": "function"}], repo_root=tmp_path, output_dir=tmp_path / "async",
    )
    assert result["status"] == "call_failed"


def test_publication_requires_current_path_validation():
    from component_method.library_publish.component_cards import component_card
    with pytest.raises(ValueError, match="requires current entrypoint_capabilities"):
        component_card({"entrypoints": [{"name": "f", "purpose": "operation"}],
                        "local_validation": {"status": "validated"}}, "def f(): return 1", "id", "f.py")


def test_readme_preserves_source_reference_notes_and_usage_metadata():
    from component_method.library_publish.component_cards import component_card, component_readme
    item = {"name": "Fill mark", "capability": "Draw filled shapes",
            "members": [{"file_id": "area.py", "unit_id": "class:Area"}],
            "entrypoints": [{"name": "Area", "kind": "class", "purpose": "Fill polygons"}],
            "applicability": {"conditions": ["A Mark interface is available"], "non_applicability": []},
            "integration_steps": ["Override the coordinate hook and preserve color resolution"],
            "relationships": ["Area extends Mark"],
            "evidence": [
                {"file_id": "area.py", "line_start": 10, "line_end": 20,
                 "claim": "The legend hook uses the shared color and fill resolution"},
                {"file_id": "tests/test_area.py", "claim": "Two callers prove reuse"}],
            "local_validation": {"validation": {"entrypoint_capabilities": [
                {"entrypoint": "Area", "path": "Area", "contract": "Construct a fill mark",
                 "validation_status": "validated"}]}}}
    card = component_card(item, "class Area: pass", "component-001", "component.py")
    readme = component_readme(card)
    assert "The legend hook uses the shared color and fill resolution" in readme
    assert "Area extends Mark" in readme and "Draw filled shapes" in readme
    assert "A Mark interface is available" in readme and item["integration_steps"][0] in readme
    assert "Two callers prove reuse" not in readme
    assert "```json" not in readme and '"conditions"' not in readme
    assert "**Applicable when**" in readme
    assert "1. Override the coordinate hook" in readme
    assert card["available"][0]["path"] == "Area"


def test_effective_extraction_schema_requests_applicability_and_integration(tmp_path):
    from component_method.component_build.experiment import load_component_contract, resolve_prompt
    from component_method.component_build.extraction.service import ExtractionRequest, _task_prompt
    contract = load_component_contract(None)
    assert {"applicability", "integration_steps"} <= set(contract["optional_fields"])
    request = ExtractionRequest(workspace_root=tmp_path, output_dir=tmp_path,
                                strategy="component_method", workspace_scope="community",
                                output_contract=contract)
    prompt = _task_prompt(request, resolve_prompt(None, "extraction/extract_system.txt"))
    assert '"applicability": {' in prompt and '"integration_steps": []' in prompt
    assert "source-supported applicability conditions and integration_steps" in prompt


@pytest.mark.parametrize("settings", [
    {"index_format": "jsonl"}, {"library_layout": "flat"}, {"retrieval_top_k": 5},
    {"sort_by": "capability"},
])
def test_bundle_settings_accept_only_current_layout(tmp_path, settings):
    from component_method.component_build.experiment import load_bundle_config
    (tmp_path / "bundle_config.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        load_bundle_config(tmp_path)


def test_readme_renders_nested_metadata_as_markdown_without_truncating_examples():
    from component_method.library_publish.component_cards import component_card, component_readme
    item = {"name": "Transform", "members": [], "entrypoints": [{"name": "Transform", "kind": "class"}],
            "dependencies": [{"module": "numpy", "requirement": ">=1.0"}],
            "applicability": {"conditions": ["Numeric vectors"], "non_applicability": ["Ragged arrays"]},
            "integration_steps": [{"operation": "Construct", "details": ["Supply a vector"]}],
            "invariants": ["Shape is preserved"], "variation_points": ["Override the mapping"],
            "local_validation": {"validation": {"entrypoint_capabilities": [
                {"entrypoint": "Transform", "path": "Transform", "validation_status": "validated",
                 "example": "Transform([1, 2])\n" + "# source details\n" * 50}]}}}
    readme = component_readme(component_card(item, "class Transform: pass", "id", "component.py"))
    for value in ["numpy", ">=1.0", "Numeric vectors", "Ragged arrays", "Supply a vector", "Shape is preserved", "Override the mapping"]:
        assert value in readme
    assert "```json" not in readme and '"module"' not in readme
    assert readme.count("# source details") == 50


def test_omitted_class_methods_are_explicitly_unverified(tmp_path):
    from component_method.library_publish.component_cards import component_card
    item = {"entrypoints": [{"name": "Transform", "kind": "class"}],
            "local_validation": {"status": "validated", "validation": {"entrypoint_capabilities": [
                {"entrypoint": "Transform", "path": "Transform", "validation_status": "validated"}
            ]}}}
    card = component_card(item, "class Transform:\n    def log(self, x): return x\n", "id", "f.py")
    assert card["unavailable"][0]["path"] == "Transform.log"
    assert card["unavailable"][0]["validation_status"] == "unverified"


def cache_fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ["module.py", "helper.py", "unrelated.py"]:
        (repo / name).write_text("source content\n")
    payload = {"candidate": {"name": "operation", "members": [{"file_id": "module.py"}]},
               "proposed_component": {"library": {"content": "def operation(): return 1"}}}
    review = {"status": "confirmed", "validation_dependencies": {
        "complete": True, "files": ["module.py", "helper.py"], "search_scopes": []}}
    return repo, payload, review, SimpleNamespace(model="model", base_url="endpoint")


def test_shared_review_hits_across_snapshots_and_invalidates_dependencies_and_prompt(tmp_path):
    repo, payload, review, runner = cache_fixture(tmp_path)
    count = []
    def operation():
        count.append(1)
        return deepcopy(review)
    def run(query=payload):
        return cached_review(tmp_path / "cache", repo, query, runner, tmp_path / "experiment", operation)[1]["status"]
    assert run() == "miss" and run() == "hit"
    import shutil
    snapshot = tmp_path / "snapshot-two"
    shutil.copytree(repo, snapshot)
    assert cached_review(tmp_path / "cache", snapshot, payload, runner, tmp_path / "experiment", operation)[1]["status"] == "hit"
    (repo / "unrelated.py").write_text("different task mask\n")
    assert run() == "hit"
    (repo / "helper.py").write_text("changed dependency\n")
    assert run() == "miss"
    changed = deepcopy(payload)
    changed["proposed_component"]["library"]["content"] = "def operation(): return 2"
    assert run(changed) == "miss"
    prompt = tmp_path / "experiment/prompts/validation/review_system.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Changed review policy")
    assert run() == "miss"
    assert len(count) == 4


def test_shared_review_invalidates_installed_default_agent_config(tmp_path):
    from component_method.component_build.extraction.runner import MiniSweComponentRunner
    repo, payload, review, _ = cache_fixture(tmp_path)
    runner = object.__new__(MiniSweComponentRunner)
    runner.model, runner.base_url, runner.image_id = "fixture", "fixture", "fixture"
    runner.default_config = tmp_path / "mini.yaml"
    runner.default_config.write_text("agent:\n  observation_template: version-one\n")
    calls = []

    def review_operation():
        calls.append(1)
        return deepcopy(review)

    def run():
        return cached_review(tmp_path / "cache", repo, payload, runner, None, review_operation)[1]["status"]

    assert run() == "miss" and run() == "hit"
    runner.default_config.write_text("agent:\n  observation_template: version-two\n")
    assert run() == "miss" and run() == "hit"
    assert len(calls) == 2


def test_search_scope_changes_and_incomplete_manifests_are_not_reused(tmp_path):
    repo, payload, review, runner = cache_fixture(tmp_path)
    review["validation_dependencies"]["search_scopes"] = ["."]
    def run():
        return cached_review(tmp_path / "cache", repo, payload, runner, None, lambda: deepcopy(review))[1]["status"]
    assert run() == "miss" and run() == "hit"
    (repo / "unrelated.py").write_text("changes repository-wide search results")
    assert run() == "miss"
    review["validation_dependencies"]["complete"] = False
    # A different prompt guarantees we are exercising the incomplete response.
    payload["candidate"]["name"] = "new operation"
    assert run() == "not_cacheable" and run() == "not_cacheable"


def test_concurrent_same_review_runs_model_operation_once(tmp_path):
    repo, payload, review, runner = cache_fixture(tmp_path)
    count = []
    def operation():
        count.append(1)
        return deepcopy(review)
    def run(_):
        return cached_review(tmp_path / "cache", repo, payload, runner, None, operation)[1]["status"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ["hit", "miss"]
    assert len(count) == 1


def test_shell_dependencies_include_uncited_files_and_conservative_script_scope(tmp_path):
    repo, _, _, _ = cache_fixture(tmp_path)
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(json.dumps({"messages": [{"role": "assistant", "extra": {"actions": [
        {"command": "sed -n '1,20p' /testbed/helper.py"}, {"command": "rg -n missing_symbol module.py"},
    ]}}]}))
    assert observed_dependencies(trajectory, repo) == {"files": ["helper.py"], "search_scopes": ["module.py"]}
    trajectory.write_text(json.dumps({"messages": [{"role": "assistant", "extra": {"actions": [
        {"command": "python -c 'inspect_arbitrary_files()'"},
    ]}}]}))
    assert observed_dependencies(trajectory, repo)["search_scopes"] == ["."]
