from component_method.protocol_candidates.protocol_recall import (
    _select_coverage_v2,
    recall_candidates,
)


def _semantic(*pairs):
    return {"signal": "semantic", "pairs": list(pairs), "units": []}


def _pair(file_a, unit_a, file_b, unit_b, cosine):
    return {
        "file_a": file_a,
        "unit_a": unit_a,
        "file_b": file_b,
        "unit_b": unit_b,
        "cosine": cosine,
    }


def _candidate(candidate_id, units, relation, key, score=1.0):
    first, second, *expanded = units
    return {
        "candidate_id": candidate_id,
        "units": [
            {"file_id": file_id, "unit_id": unit_id, "kind": "function"}
            for file_id, unit_id in units
        ],
        "seed_units": [
            {"file_id": file_id, "unit_id": unit_id, "kind": "function"}
            for file_id, unit_id in (first, second)
        ],
        "seed_evidence": {
            "seed_kind": "protocol_supported",
            "signals_passed": [],
            "signals": {},
            "direct_relations": [{"relation": relation, "key": key}],
        },
        "expanded_units": [
            {
                "file_id": file_id,
                "unit_id": unit_id,
                "relation": relation,
                "key": key,
                "from_file_id": first[0],
                "from_unit_id": first[1],
                "relation_score": 1.0,
            }
            for file_id, unit_id in expanded
        ],
        "truncated_units": [],
        "relation_kinds": [relation],
        "signals_hit": ["semantic"],
        "score": score,
    }


def test_protocol_support_recovers_low_semantic_cross_role_candidate():
    sources = [
        {
            "file_id": "typing_tools.py",
            "source_code": """
from typing import get_args, get_origin

class TypeParser:
    def parse(self, value):
        origin = get_origin(value)
        return origin, get_args(value)
""",
        },
        {
            "file_id": "hashing.py",
            "source_code": """
from typing import get_args, get_origin

def bytes_repr_type(value):
    origin = get_origin(value)
    return origin, get_args(value)
""",
        },
        {
            "file_id": "specs.py",
            "source_code": """
from typing_tools import TypeParser

def normalize_spec(value):
    return TypeParser().parse(value)
""",
        },
    ]
    semantic = _semantic(
        _pair("typing_tools.py", "method:TypeParser.parse", "hashing.py", "function:bytes_repr_type", 0.49),
        _pair("typing_tools.py", "method:TypeParser.parse", "specs.py", "function:normalize_spec", 0.83),
    )
    result = recall_candidates(sources, [semantic], {"top_candidates": 10})
    candidate = next(
        item for item in result["candidates"]
        if {("typing_tools.py", "method:TypeParser.parse"), ("hashing.py", "function:bytes_repr_type")}
        <= {(unit["file_id"], unit["unit_id"]) for unit in item["units"]}
    )
    units = {(unit["file_id"], unit["unit_id"]) for unit in candidate["units"]}
    assert ("specs.py", "function:normalize_spec") in units
    assert "shared_protocol_symbol" in candidate["relation_kinds"]
    assert "definition_reference" in candidate["relation_kinds"]


def test_sibling_methods_are_protocol_relations():
    sources = [
        {"file_id": "first.py", "source_code": "class First:\n    def dispatch(self, value):\n        return value\n"},
        {"file_id": "second.py", "source_code": "class Second:\n    def dispatch(self, value):\n        return value + 1\n"},
    ]
    semantic = _semantic(
        _pair("first.py", "method:First.dispatch", "second.py", "method:Second.dispatch", 0.45)
    )
    result = recall_candidates(sources, [semantic], {"top_candidates": 5})
    assert result["candidates"]
    assert "sibling_method" in result["candidates"][0]["relation_kinds"]


def test_coverage_policy_compresses_only_after_v1_relevance_pooling():
    sources = [
        {"file_id": "first.py", "source_code": "def dispatch(value):\n    return value\n"},
        {"file_id": "second.py", "source_code": "def dispatch(value):\n    return value + 1\n"},
        {"file_id": "third.py", "source_code": "def dispatch(value):\n    return value + 2\n"},
    ]
    semantic = _semantic(
        _pair("first.py", "function:dispatch", "second.py", "function:dispatch", 0.9),
        _pair("first.py", "function:dispatch", "third.py", "function:dispatch", 0.8),
    )
    result = recall_candidates(sources, [semantic], {
        "selection_policy": "marginal_coverage_v2",
        "candidate_pool_size": 2,
        "top_candidates": 2,
        "min_candidates_per_relation": 0,
        "min_protocol_supported_candidates": 0,
    })

    assert result["stats"]["selection_policy"] == "marginal_coverage_v2"
    assert result["stats"]["candidate_pool_policy"] == "score_topk_v1"
    assert result["stats"]["candidate_pool_count"] <= 2
    assert result["stats"]["precompression_generated_candidate_count"] >= len(result["candidates"])


def test_candidate_limits_are_enforced_deterministically():
    sources = [
        {
            "file_id": f"module_{index}.py",
            "source_code": f"def handler_{index}(old_state):\n    return normalize(old_state)\n",
        }
        for index in range(10)
    ]
    pairs = [
        _pair("module_0.py", "function:handler_0", "module_1.py", "function:handler_1", 0.9)
    ]
    cfg = {
        "top_candidates": 5,
        "max_candidate_units": 5,
        "max_candidate_files": 4,
        "max_expanded_per_relation": 2,
    }
    first = recall_candidates(sources, [_semantic(*pairs)], cfg)
    second = recall_candidates(sources, [_semantic(*pairs)], cfg)
    assert first == second
    assert all(len(item["units"]) <= 5 for item in first["candidates"])
    assert all(len(item["members"]) <= 4 for item in first["candidates"])
    assert first["candidates"][0]["truncated_units"]


def test_coverage_selection_merges_exact_unit_sets_and_relation_provenance():
    units = [("a.py", "function:a"), ("b.py", "function:b")]
    selected, stats = _select_coverage_v2(
        [
            _candidate("first", units, "shared_call", "normalize", score=2.0),
            _candidate("second", units, "shared_registration", "serializer", score=1.0),
        ],
        {"top_candidates": 10, "candidate_overlap_jaccard": 0.5},
    )

    assert len(selected) == 1
    assert selected[0]["relation_kinds"] == ["shared_call", "shared_registration"]
    assert selected[0]["compression"]["source_seed_count"] == 2
    assert len(selected[0]["relation_edges"]) == 2
    assert stats["exact_duplicates_merged"] == 1


def test_coverage_selection_suppresses_overlap_without_new_protocol_information():
    selected, stats = _select_coverage_v2(
        [
            _candidate(
                "primary",
                [("a.py", "function:a"), ("b.py", "function:b"), ("c.py", "function:c")],
                "shared_call",
                "normalize",
                score=2.0,
            ),
            _candidate(
                "repeated",
                [("a.py", "function:a"), ("b.py", "function:b"), ("d.py", "function:d")],
                "shared_call",
                "normalize",
                score=1.5,
            ),
        ],
        {"top_candidates": 10, "candidate_overlap_jaccard": 0.5},
    )

    assert [item["candidate_id"] for item in selected] == ["primary"]
    assert stats["stopped_before_limit"]
    assert stats["high_overlap_candidates_suppressed"] == 1
    assert stats["unselected_candidates"][0]["reason"] == "high_overlap_without_unique_protocol"
    assert selected[0]["compression"]["absorbed_candidates"][0]["candidate_id"] == "repeated"


def test_coverage_selection_keeps_overlapping_candidate_with_unique_protocol_role():
    selected, _ = _select_coverage_v2(
        [
            _candidate(
                "normalizer",
                [("a.py", "function:a"), ("b.py", "function:b"), ("c.py", "function:c")],
                "shared_call",
                "normalize",
                score=2.0,
            ),
            _candidate(
                "serializer",
                [("a.py", "function:a"), ("b.py", "function:b"), ("d.py", "function:d")],
                "shared_registration",
                "serializer",
                score=1.0,
            ),
        ],
        {"top_candidates": 10, "candidate_overlap_jaccard": 0.5},
    )

    assert {item["candidate_id"] for item in selected} == {"normalizer", "serializer"}
    assert selected[1]["selection"]["new_role_count"] == 1

