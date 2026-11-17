"""Task-blind handoff from protocol recall to extraction."""

from pathlib import Path

from component_method.protocol_candidates.extraction import (
    ProtocolPacketConfig,
    pack_protocol_candidates,
    protocol_packet_extraction_request,
)
from component_method.component_build.extraction.service import _task_prompt


def _candidate(candidate_id, units):
    return {
        "candidate_id": candidate_id,
        "units": [
            {"file_id": file_id, "unit_id": unit_id, "kind": "function"}
            for file_id, unit_id in units
        ],
        "seed_evidence": {"direct_relations": [{"relation": "private", "key": "hidden"}]},
    }


def test_packing_is_deterministic_and_preserves_all_candidate_units():
    candidates = [
        _candidate("first", [("a.py", "function:a"), ("b.py", "function:b")]),
        _candidate("second", [("a.py", "function:a"), ("b.py", "function:b2")]),
        _candidate("third", [("z.py", "function:z"), ("y.py", "function:y")]),
    ]
    config = ProtocolPacketConfig(min_shared_units=1, min_jaccard=0.2, max_units=5, max_files=5)
    first = pack_protocol_candidates(candidates, config=config)
    second = pack_protocol_candidates(candidates, config=config)

    assert first == second
    assert len(first) == 2
    assert first[0]["candidate_ids"] == ["first", "second"]
    assert first[0]["candidate_ranks"] == [1, 2]
    packed_units = {
        (unit["file_id"], unit["unit_id"])
        for packet in first
        for unit in packet["primary_units"]
    }
    expected_units = {
        (unit["file_id"], unit["unit_id"])
        for candidate in candidates
        for unit in candidate["units"]
    }
    assert packed_units == expected_units


def test_packet_request_exposes_only_primary_source_scope(tmp_path):
    packet = pack_protocol_candidates([
        _candidate("first", [("a.py", "function:a"), ("b.py", "function:b")]),
    ])[0]
    request = protocol_packet_extraction_request(
        repository_root=tmp_path,
        output_root=tmp_path / "out",
        packet=packet,
    )

    assert request.workspace_scope == "candidate"
    assert request.expected_files == ["a.py", "b.py"]
    assert set(request.context) == {"primary_extraction_files", "primary_extraction_units"}
    rendered = _task_prompt(request, "Extract shared source capabilities.")
    assert "Focus extraction on the listed primary source files and units" in rendered
    assert "Additional task context" not in rendered
    assert "candidate_ids" not in rendered
    assert "seed_evidence" not in rendered
    assert "direct_relations" not in rendered
    assert "task description" not in rendered.lower()
    assert str(Path(tmp_path)) not in rendered


def test_packet_limits_prevent_oversized_merge():
    candidates = [
        _candidate("first", [("a.py", "function:a"), ("b.py", "function:b")]),
        _candidate("second", [("a.py", "function:a"), ("c.py", "function:c")]),
    ]
    packets = pack_protocol_candidates(
        candidates,
        config=ProtocolPacketConfig(
            min_shared_units=1,
            min_jaccard=0.2,
            max_units=2,
            max_files=2,
        ),
    )
    assert len(packets) == 2



def test_packet_request_limits_source_units_to_primary_units(tmp_path):
    (tmp_path / "sample.py").write_text(
        "def selected(value):\n    return value + 1\n\ndef context(value):\n    return value - 1\n"
    )
    backend = __import__("component_method.languages.python.backend", fromlist=["PythonBackend"]).PythonBackend()
    units = backend.extract_units("sample.py", (tmp_path / "sample.py").read_text())
    selected = next(unit for unit in units if unit.kind == "function" and unit.display_name == "selected")
    packet = {
        "packet_id": "protocol_packet_primary_units",
        "language": "python",
        "backend_id": "python@1",
        "primary_files": ["sample.py"],
        "primary_units": [{"file_id": "sample.py", "unit_id": selected.unit_key,
                          "unit_key": selected.unit_key}],
    }
    request = protocol_packet_extraction_request(
        repository_root=tmp_path,
        output_root=tmp_path / "out",
        packet=packet,
    )
    assert [unit["qualified_name"] for unit in request.context["source_units"]] == ["selected"]
