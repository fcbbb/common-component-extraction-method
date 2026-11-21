"""Unreviewed publication stays explicit and does not masquerade as reviewed."""

import json
from pathlib import Path

import pytest

from component_method.library_publish import publish_unreviewed


def _component() -> dict:
    return {
        "status": "draft_ready",
        "component_id": "component-1",
        "name": "Identity helper",
        "summary": "Returns the input unchanged.",
        "members": [{"file_id": "module.py", "unit_id": "function:identity"}],
        "evidence": [
            {
                "file_id": "module.py",
                "line_start": 1,
                "line_end": 2,
                "claim": "Copies the identity implementation.",
            }
        ],
        "entrypoints": [
            {"name": "identity", "kind": "function", "purpose": "Return the input"}
        ],
        "limitations": [],
        "protocol_contract": {
            "capability_family": "transform",
            "semantic_domain": "numeric",
            "extension_trigger": "identity conversion",
            "covered_variants": ["identity"],
            "downstream_guarantee": "same value",
            "consumers": [
                {"file_id": "consumer.py", "unit_id": "function:use"},
                {"file_id": "other.py", "unit_id": "function:use"},
            ],
            "reuse_interface": "identity(x)",
            "boundary": "numeric inputs",
        },
        "library": {"content": "def identity(value):\n    return value\n"},
    }


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "task"
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"task_id": "task-a", "repository": "org/repo", "source_commit": "abc"}),
        encoding="utf-8",
    )
    frozen = root / "inputs" / "frozen_components.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_packet_id": "packet-1",
                        "component_id": "component-1",
                        "component": _component(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def test_unreviewed_publish_marks_every_audit_record(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    monkeypatch.setattr(publish_unreviewed, "ROOT", root)
    monkeypatch.setattr(publish_unreviewed, "PROJECT", tmp_path)

    publish_unreviewed.main()

    library = root / "outputs" / "full_library"
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["component_count"] == 1
    assert manifest["review_status"] == "not_run"
    assert manifest["discovery_audit_status"] == "task_blind_unreviewed"
    audit = json.loads(
        (library / manifest["components"][0]["audit_file"]).read_text(encoding="utf-8")
    )
    assert audit["review_status"] == "not_run"
    assert audit["protocol_status"] == "unreviewed"
    assert (library / "components" / "component-001" / "component.py").is_file()


def test_unreviewed_publish_refuses_to_overwrite_a_library(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    monkeypatch.setattr(publish_unreviewed, "ROOT", root)
    monkeypatch.setattr(publish_unreviewed, "PROJECT", tmp_path)
    library = root / "outputs" / "full_library"
    library.mkdir(parents=True)
    (library / "existing").write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="preserving existing component library"):
        publish_unreviewed.main()