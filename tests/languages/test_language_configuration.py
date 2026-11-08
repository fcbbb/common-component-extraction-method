import json

import pytest

from component_method.workflow import batch_common
from tools import prepare_workspace


def method(**config):
    return {"task_model": "test", "embedding": {}, "pipeline": {}, **config}


def test_workspace_default_and_legacy_language():
    for config in ({}, {"language": "python"}):
        value = prepare_workspace.workspace_config(method(**config), "https://example.invalid")
        assert value["languages"] == [{"id": "python"}]


@pytest.mark.parametrize("task_languages", [None, {"language": "python"}])
def test_task_language_override_and_method_inheritance(monkeypatch, tmp_path, task_languages):
    task = {"repo": "org/repo", "image_name": "image", **(task_languages or {})}
    documents = {
        "task.json": task, "provenance.json": {"source_subdir": "src"},
        "manifest.json": {"source_commit": "abc"},
    }
    monkeypatch.setattr(prepare_workspace, "read_json", lambda path: documents[path.name])
    monkeypatch.setattr(prepare_workspace, "sha256", lambda path: "0" * 64)
    pipeline = {key: 1 for key in (
        "agent_timeout_seconds", "extraction_workers", "review_workers", "max_review_repair_rounds"
    )}
    pipeline["packet_config"] = {}
    config = method(language="cpp")
    config["pipeline"] = pipeline
    value = prepare_workspace.task_config("task", "https://example.invalid", config,
                                          tmp_path / "candidate.json", tmp_path / "repo")
    assert value["languages"] == [{"id": "python" if task_languages else "cpp"}]


def test_existing_workspace_config_is_normalized_without_rewriting(monkeypatch, tmp_path):
    monkeypatch.setattr(batch_common, "ROOT", tmp_path)
    config_path = tmp_path / "config.json"
    original = '{"language": "python", "experiment_id": "frozen"}\n'
    config_path.write_text(original, encoding="utf-8")
    assert batch_common.config()["languages"] == [{"id": "python"}]
    assert config_path.read_text(encoding="utf-8") == original
    (tmp_path / "tasks.json").write_text(json.dumps({"tasks": [{"instance_id": "one"}]}))
    assert batch_common.tasks()[0]["languages"] == [{"id": "python"}]
    config_path.write_text('{"languages": [{"id": "cpp"}]}', encoding="utf-8")
    assert batch_common.tasks()[0]["languages"] == [{"id": "cpp"}]
    (tmp_path / "tasks.json").write_text(json.dumps({
        "tasks": [{"instance_id": "one", "language": "python"}]
    }))
    assert batch_common.tasks()[0]["languages"] == [{"id": "python"}]
