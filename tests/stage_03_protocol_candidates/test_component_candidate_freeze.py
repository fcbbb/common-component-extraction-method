import json
from pathlib import Path

from component_method.protocol_candidates import (
    freeze_extraction_directory,
    freeze_extraction_records,
)


def component(component_id, name, members):
    return {
        "component_id": component_id,
        "status": "draft_ready",
        "name": name,
        "summary": "Shared behavior",
        "type": "repeated_implementation",
        "confidence": "high",
        "relationships": ["shared"],
        "invariants": ["stable"],
        "variation_points": [],
        "members": members,
        "evidence": [{"file_id": members[0]["file_id"], "line_start": 1, "line_end": 1, "claim": "copy"}],
        "library": {"path": "components/x/common.py", "content": "def shared():\n    return 1\n"},
        "entrypoints": [{"name": "shared", "kind": "function", "purpose": "Return one."}],
        "dependencies": [],
        "limitations": [],
        "guidance": {},
        "applicability": {"conditions": [], "non_applicability": []},
        "integration_steps": [],
    }


def test_freeze_exactly_deduplicates_members_without_task_inputs():
    members = [
        {"file_id": "a.py", "unit_id": "function:shared"},
        {"file_id": "b.py", "unit_id": "function:shared"},
    ]
    records = [
        {"batch_id": "packet-a", "source_component_id": "first", "component": component("first", "Shared", members)},
        {"batch_id": "packet-b", "source_component_id": "second", "component": component("second", "Other label", list(reversed(members)))},
    ]

    frozen, manifest = freeze_extraction_records(records)

    assert len(frozen) == 1
    assert frozen[0]["source_regions"] == ["packet-a", "packet-b"]
    assert frozen[0]["component_draft"]["origin_strategy"] == "protocol_candidate_blind_extraction"
    assert manifest["task_information_used"] is False
    assert manifest["duplicates_removed"] == 1


def test_freeze_reads_only_schema_accepted_components(tmp_path: Path):
    batch = tmp_path / "packet-a"
    batch.mkdir()
    accepted = component("accepted", "Accepted", [{"file_id": "a.py", "unit_id": "function:a"}])
    rejected = component("rejected", "Rejected", [{"file_id": "b.py", "unit_id": "function:b"}])
    (batch / "extraction_response.json").write_text(
        json.dumps({"components": [accepted, rejected]}), encoding="utf-8"
    )
    (batch / "extraction_schema_validation.json").write_text(
        json.dumps({"accepted_component_ids": ["accepted"]}), encoding="utf-8"
    )

    frozen, manifest = freeze_extraction_directory(tmp_path)

    assert [item["name"] for item in frozen] == ["Accepted"]
    assert manifest["accepted_extraction_count"] == 1
