from copy import deepcopy
from functools import partial
import gzip
import hashlib
import json
import sys
from types import SimpleNamespace

import docker
import pytest

from component_method.component_build import pipeline
from component_method.component_build.validation.artifact_service import validate_artifact_component
from component_method.workflow import multilanguage
from test_artifact_pipeline import fake_executor, fixture_component


@pytest.mark.parametrize("outcomes, expected_code, published_count", [
    (["validated"], 0, 1),
    (["failed"], 1, 0),
    (["validated", "failed"], 1, 1),
    (["rejected"], 0, 0),
    (["unverified"], 0, 0),
    ([], 0, 0),
])
def test_cli_exit_code_reflects_real_pipeline_results(
    tmp_path, monkeypatch, capsys, outcomes, expected_code, published_count,
):
    component, review, repository = fixture_component(tmp_path, "python")
    drafts = [{**deepcopy(component), "component_id": f"addition-{index}"} for index in range(len(outcomes))]
    pending = iter(outcomes)

    class FixtureAgent:
        def __init__(self, **kwargs):
            pass

        def run_workspace_agent(self, **kwargs):
            if kwargs.get("agent_role") == "review":
                result = deepcopy(review)
                outcome = next(pending)
                if outcome == "failed":
                    result["smoke_test"]["cases"][0]["backend_id"] = "python@invalid"
                elif outcome in {"rejected", "unverified"}:
                    result["status"] = "rejected" if outcome == "rejected" else "uncertain"
                return result
            return {"status": "ready" if drafts else "no_component", "components": deepcopy(drafts),
                    "workspace_audit": {"checked_files": [m["file_id"] for m in component["members"]], "gaps": []}}

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"repository_root": str(repository.repo_root), "languages": [{"id": "python"}],
                                  "runtime_image": "fixture", "model": "fixture", "max_repairs": 0}))
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"candidates": [{"candidate_id": "addition", "language": "python",
                                                     "backend_id": "python@1", "units": component["members"]}]}))
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["multilanguage", "--config", str(config), "--candidates", str(candidates),
                                     "--output", str(output)])
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(multilanguage, "OfficialImageExtractionRunner", FixtureAgent)
    monkeypatch.setattr(docker, "from_env", lambda: SimpleNamespace(
        images=SimpleNamespace(get=lambda image: SimpleNamespace(id="sha256:fixture")), close=lambda: None,
    ))
    monkeypatch.setattr(pipeline, "validate_artifact_component", partial(validate_artifact_component, executor=fake_executor))

    assert multilanguage.main() == expected_code
    summary = json.loads((output / "build/summary.json").read_text())
    assert [item["status"] for item in summary["results"]] == outcomes
    assert summary["published_count"] == published_count
    assert json.loads(capsys.readouterr().out) == summary


def test_workflow_unit_cache_requires_current_source_hashes(tmp_path):
    source = "def selected(value):\n    return value + 1\n"
    source_path = tmp_path / "sample.py"
    source_path.write_text(source)
    cache = tmp_path / "units.jsonl.gz"
    row = {
        "schema": "source-unit-v2",
        "language": "python",
        "backend_id": "python@1",
        "file_id": "sample.py",
        "unit_key": "unit-key",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    }
    with gzip.open(cache, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    sources = [{"file_id": "sample.py", "source_code": source}]
    assert multilanguage._load_cached_units(
        cache, sources, {("python", "python@1")}
    ) == {("sample.py", "unit-key", "python", "python@1")}
    with pytest.raises(ValueError, match="source changed"):
        multilanguage._load_cached_units(
            cache,
            [{"file_id": "sample.py", "source_code": source + "# changed\n"}],
            {("python", "python@1")},
        )
