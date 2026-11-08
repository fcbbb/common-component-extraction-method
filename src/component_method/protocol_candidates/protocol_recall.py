"""Task-blind candidate recall with bounded protocol-relation expansion.

Similarity signals find code that looks alike.  This module keeps those signals
as seeds, then adds one bounded layer of source-backed relations so that
different roles in one repository protocol can be inspected together.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


from component_method.languages.registry import default_backend

Node = tuple[str, str]

DEFAULT_CFG: dict[str, Any] = {
    "semantic_seed_min_cosine": 0.78,
    "semantic_supported_min_cosine": 0.35,
    "clone": {"min_shared": 40, "min_containment": 0.35, "min_runs": 1},
    "skeleton": {"min_shared": 18, "min_containment": 0.55, "min_runs": 1},
    "max_relation_frequency": 12,
    "max_definition_references": 20,
    "max_expanded_per_relation": 4,
    "max_candidate_units": 20,
    "max_candidate_files": 8,
    "max_seed_edges": 4000,
    "top_candidates": 40,
    "protocol_candidate_reserve": 24,
    "min_candidates_per_relation": 3,
    "min_protocol_supported_candidates": 8,
    "selection_policy": "score_topk_v1",
    "candidate_overlap_jaccard": 0.5,
    "coverage_role_weight": 8.0,
    "coverage_relation_weight": 3.0,
    "coverage_edge_weight": 1.0,
    "coverage_unit_weight": 0.25,
}

def build_profiles(sources: Iterable[dict[str, str]], backend=None) -> dict[Node, UnitProfile]:
    backend = backend or default_backend()
    result = {}
    for entry in sources:
        for unit in backend.extract_units(entry["file_id"], entry["source_code"]):
            p = backend.build_profile(unit)
            node = (unit.file_id, unit.unit_key if getattr(backend, "canonical_units", False)
                    else unit.metadata.get("legacy_unit_id", unit.unit_key))
            result[node] = UnitProfile(
                node=node, kind=unit.kind, source_code=unit.source_code,
                owner_name=p.owner_name, member_name=p.member_name,
                defined_symbols=set(p.defined_symbols), references=set(p.referenced_symbols),
                calls=set(p.calls) - set(p.ignored_calls), protocol_symbols=set(p.protocol_markers),
                registration_keys=set(p.registration_keys),
                flow_names=set(p.flow_names) - set(p.ignored_names),
                state_fields=set(p.state_reads) | set(p.state_writes),
                member_calls=set(p.related_members), lifecycle_names=set(p.lifecycle_names),
            )
    return result


@dataclass
class UnitProfile:
    node: Node
    kind: str
    source_code: str
    owner_name: str | None = None
    member_name: str = ""
    defined_symbols: set[str] = field(default_factory=set)
    references: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    protocol_symbols: set[str] = field(default_factory=set)
    registration_keys: set[str] = field(default_factory=set)
    flow_names: set[str] = field(default_factory=set)
    state_fields: set[str] = field(default_factory=set)
    member_calls: set[str] = field(default_factory=set)
    lifecycle_names: set[str] = field(default_factory=set)


def _add_relation(
    relations: dict[Node, dict[Node, list[dict[str, Any]]]],
    first: Node,
    second: Node,
    kind: str,
    key: str,
) -> None:
    if first == second:
        return
    evidence = {"relation": kind, "key": key}
    bucket = relations[first][second]
    if evidence not in bucket:
        bucket.append(evidence)
    reverse = relations[second][first]
    if evidence not in reverse:
        reverse.append(evidence)


def _index_relations(
    profiles: dict[Node, UnitProfile],
    cfg: dict[str, Any],
) -> dict[Node, dict[Node, list[dict[str, Any]]]]:
    relations: dict[Node, dict[Node, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    max_frequency = int(cfg["max_relation_frequency"])

    def connect_shared(kind: str, values: dict[Node, set[str]], common: set[str] | None = None) -> None:
        inverse: dict[str, list[Node]] = defaultdict(list)
        for node in sorted(values):
            for key in sorted(values[node]):
                if not key or (common and key in common):
                    continue
                inverse[key].append(node)
        for key in sorted(inverse):
            nodes = inverse[key]
            unique = sorted(set(nodes))
            if not 2 <= len(unique) <= max_frequency:
                continue
            for first, second in itertools.combinations(unique, 2):
                if first[0] != second[0]:
                    _add_relation(relations, first, second, kind, key)

    connect_shared("shared_call", {node: p.calls for node, p in profiles.items()})
    connect_shared(
        "shared_protocol_api",
        {node: {key for key in p.protocol_symbols if key.startswith("call:")} for node, p in profiles.items()},
    )
    connect_shared(
        "shared_protocol_symbol",
        {node: {key for key in p.protocol_symbols if not key.startswith("call:")} for node, p in profiles.items()},
    )
    connect_shared("shared_registration", {node: p.registration_keys for node, p in profiles.items()})
    connect_shared(
        "shared_flow_name",
        {node: {name for name in p.flow_names if name not in p.lifecycle_names} for node, p in profiles.items()},
    )
    connect_shared(
        "lifecycle_flow",
        {node: {name for name in p.flow_names if name in p.lifecycle_names} for node, p in profiles.items()},
    )

    methods: dict[str, list[Node]] = defaultdict(list)
    for node in sorted(profiles):
        profile = profiles[node]
        if profile.owner_name and profile.member_name:
            methods[profile.member_name].append(node)
    for method_name in sorted(methods):
        nodes = methods[method_name]
        unique = sorted(set(nodes))
        if 2 <= len(unique) <= int(cfg["max_definition_references"]):
            for first, second in itertools.combinations(unique, 2):
                if first[0] != second[0]:
                    _add_relation(relations, first, second, "sibling_method", method_name)

    definitions: dict[str, list[Node]] = defaultdict(list)
    for node in sorted(profiles):
        profile = profiles[node]
        for symbol in sorted(profile.defined_symbols):
            definitions[symbol].append(node)
    max_refs = int(cfg["max_definition_references"])
    for referrer in sorted(profiles):
        profile = profiles[referrer]
        for symbol in sorted(profile.references | profile.calls):
            targets = sorted(set(definitions.get(symbol, [])))
            if not targets or len(targets) > max_refs:
                continue
            for target in targets:
                if referrer[0] != target[0]:
                    _add_relation(relations, referrer, target, "definition_reference", symbol)

    owners: dict[tuple[str, str], list[Node]] = defaultdict(list)
    for node in sorted(profiles):
        profile = profiles[node]
        if profile.owner_name:
            owners[(node[0], profile.owner_name)].append(node)
    for owner_key in sorted(owners):
        owner = owner_key[1]
        nodes = owners[owner_key]
        for first, second in itertools.combinations(sorted(nodes), 2):
            left, right = profiles[first], profiles[second]
            shared_fields = left.state_fields & right.state_fields
            direct_call = (
                right.member_name in left.member_calls
                or left.member_name in right.member_calls
            )
            if shared_fields or direct_call:
                key = ",".join(sorted(shared_fields)[:3]) or owner
                _add_relation(relations, first, second, "class_protocol_context", key)
    return relations


def _edge_key(record: dict[str, Any]) -> tuple[Node, Node] | None:
    values = (record.get("file_a"), record.get("unit_a"), record.get("file_b"), record.get("unit_b"))
    if not all(isinstance(value, str) for value in values):
        return None
    first, second = (values[0], values[1]), (values[2], values[3])
    return (first, second) if first < second else (second, first)


def _collect_signal_edges(signal_evidences: Iterable[dict[str, Any]]) -> dict[tuple[Node, Node], dict[str, dict[str, Any]]]:
    edges: dict[tuple[Node, Node], dict[str, dict[str, Any]]] = defaultdict(dict)
    for evidence in signal_evidences:
        signal = evidence.get("signal")
        records = evidence.get("pairs", []) if signal == "semantic" else evidence.get("unit_pairs", [])
        for record in records:
            key = _edge_key(record)
            if key is not None:
                edges[key][str(signal)] = dict(record)
    return edges


def _passes(signal: str, value: dict[str, Any], cfg: dict[str, Any]) -> bool:
    if signal == "semantic":
        return float(value.get("cosine", 0.0)) >= float(cfg["semantic_seed_min_cosine"])
    threshold = cfg[signal]
    return (
        int(value.get("shared_tokens", 0)) >= int(threshold["min_shared"])
        and float(value.get("containment", 0.0)) >= float(threshold["min_containment"])
        and int(value.get("n_runs", 0)) >= int(threshold["min_runs"])
    )


def _signal_strength(values: dict[str, dict[str, Any]]) -> float:
    scores = []
    if "semantic" in values:
        scores.append(float(values["semantic"].get("cosine", 0.0)))
    for signal in ("clone", "skeleton"):
        if signal in values:
            item = values[signal]
            token_score = min(1.0, math.log1p(float(item.get("shared_tokens", 0))) / math.log(201))
            scores.append(0.65 * float(item.get("containment", 0.0)) + 0.35 * token_score)
    return max(scores, default=0.0)


def _relation_weight(kind: str) -> float:
    return {
        "shared_registration": 1.0,
        "sibling_method": 0.95,
        "definition_reference": 0.9,
        "shared_protocol_api": 1.2,
        "shared_protocol_symbol": 0.9,
        "lifecycle_flow": 1.1,
        "shared_flow_name": 0.75,
        "shared_call": 0.65,
        "class_protocol_context": 0.55,
    }.get(kind, 0.5)


def _relation_records(
    relations: dict[Node, dict[Node, list[dict[str, Any]]]], first: Node, second: Node
) -> list[dict[str, Any]]:
    return relations.get(first, {}).get(second, [])


def _seed_edges(
    signal_edges: dict[tuple[Node, Node], dict[str, dict[str, Any]]],
    relations: dict[Node, dict[Node, list[dict[str, Any]]]],
    profiles: dict[Node, UnitProfile],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    seeds = []
    for (first, second), values in signal_edges.items():
        if first not in profiles or second not in profiles or first[0] == second[0]:
            continue
        direct_relations = _relation_records(relations, first, second)
        passed = sorted(signal for signal, value in values.items() if _passes(signal, value, cfg))
        semantic = float(values.get("semantic", {}).get("cosine", 0.0))
        relation_kinds = {item["relation"] for item in direct_relations}
        strong_relation = bool(
            relation_kinds
            & {
                "sibling_method", "shared_registration", "lifecycle_flow",
                "shared_protocol_api", "shared_protocol_symbol",
            }
        )
        protocol_supported = (
            semantic >= float(cfg["semantic_supported_min_cosine"])
            and (strong_relation or len(relation_kinds) >= 2)
        )
        if not passed and not protocol_supported:
            continue
        relation_score = sum(_relation_weight(item["relation"]) for item in direct_relations)
        seeds.append({
            "nodes": [first, second],
            "signals": values,
            "signals_passed": passed,
            "direct_relations": direct_relations,
            "base_score": _signal_strength(values),
            "seed_score": _signal_strength(values) + min(0.45, 0.12 * relation_score),
        })
    seeds.sort(key=lambda item: (
        -item["seed_score"],
        -len(item["direct_relations"]),
        item["nodes"],
    ))
    return seeds[: int(cfg["max_seed_edges"])]


def _candidate_from_seed(
    seed: dict[str, Any],
    relations: dict[Node, dict[Node, list[dict[str, Any]]]],
    profiles: dict[Node, UnitProfile],
    signal_edges: dict[tuple[Node, Node], dict[str, dict[str, Any]]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    seed_nodes = set(seed["nodes"])
    choices: dict[str, list[tuple[float, Node, Node, dict[str, Any]]]] = defaultdict(list)
    for source in sorted(seed_nodes):
        for target in sorted(relations.get(source, {})):
            evidence = relations[source][target]
            if target in seed_nodes or target not in profiles:
                continue
            for item in sorted(evidence, key=lambda row: (row["relation"], row["key"])):
                score = _relation_weight(item["relation"])
                pair = (source, target) if source < target else (target, source)
                score += 0.35 * _signal_strength(signal_edges.get(pair, {}))
                if target[0] not in {node[0] for node in seed_nodes}:
                    score += 0.08
                choices[item["relation"]].append((score, target, source, item))

    selected = set(seed_nodes)
    expanded: list[dict[str, Any]] = []
    truncated: list[dict[str, Any]] = []
    files = {node[0] for node in selected}
    per_relation = int(cfg["max_expanded_per_relation"])
    max_units = int(cfg["max_candidate_units"])
    max_files = int(cfg["max_candidate_files"])
    for kind in sorted(choices, key=lambda item: (-_relation_weight(item), item)):
        seen_targets: set[Node] = set()
        for score, target, source, item in sorted(
            choices[kind],
            key=lambda row: (
                -row[0], row[1], row[2], row[3]["relation"], row[3]["key"]
            ),
        ):
            if target in seen_targets:
                continue
            seen_targets.add(target)
            record = {
                "file_id": target[0], "unit_id": target[1], "relation": kind,
                "key": item["key"], "from_file_id": source[0], "from_unit_id": source[1],
                "relation_score": round(score, 4),
            }
            would_exceed = (
                len(selected) >= max_units
                or (target[0] not in files and len(files) >= max_files)
                or sum(1 for row in expanded if row["relation"] == kind) >= per_relation
            )
            if would_exceed:
                truncated.append(record)
                continue
            selected.add(target)
            files.add(target[0])
            expanded.append(record)

    relation_kinds = sorted({item["relation"] for item in seed["direct_relations"]} | {item["relation"] for item in expanded})
    protocol_score = sum(_relation_weight(kind) for kind in relation_kinds)
    direct_protocol_score = min(
        0.4,
        0.08 * len({(item["relation"], item["key"]) for item in seed["direct_relations"]}),
    )
    score = (
        float(seed["base_score"])
        + min(0.75, 0.16 * protocol_score)
        + direct_protocol_score
        + min(0.12, 0.02 * len(expanded))
        + (0.08 if len(files) >= 3 else 0.0)
        + (0.05 if len(seed["signals_passed"]) >= 2 else 0.0)
    )
    seed_units = [
        {"file_id": node[0], "unit_id": node[1], "kind": profiles[node].kind}
        for node in sorted(seed_nodes)
    ]
    units = [
        {"file_id": node[0], "unit_id": node[1], "kind": profiles[node].kind}
        for node in sorted(selected)
    ]
    digest = hashlib.sha1("\0".join(f"{n[0]}::{n[1]}" for n in sorted(selected)).encode()).hexdigest()[:12]
    return {
        "candidate_id": f"protocol_{digest}",
        "members": sorted(files),
        "n_members": len(files),
        "units": units,
        "seed_units": seed_units,
        "seed_evidence": {
            "seed_kind": "signal_supported" if seed["signals_passed"] else "protocol_supported",
            "signals_passed": seed["signals_passed"],
            "signals": seed["signals"],
            "direct_relations": seed["direct_relations"],
        },
        "expanded_units": expanded,
        "truncated_units": truncated,
        "relation_kinds": relation_kinds,
        "signals_hit": sorted(seed["signals"]),
        "score": round(score, 6),
    }


def _candidate_unit_set(candidate: dict[str, Any]) -> frozenset[Node]:
    return frozenset(
        (item["file_id"], item["unit_id"])
        for item in candidate.get("units", [])
    )


def _candidate_relation_edges(candidate: dict[str, Any]) -> frozenset[tuple[str, ...]]:
    edges: set[tuple[str, ...]] = set()
    for item in candidate.get("relation_edges", []):
        values = (
            item.get("relation"),
            item.get("key"),
            item.get("first_file_id"),
            item.get("first_unit_id"),
            item.get("second_file_id"),
            item.get("second_unit_id"),
        )
        if all(isinstance(value, str) for value in values):
            edges.add(values)
    seed_nodes = sorted(
        (item["file_id"], item["unit_id"])
        for item in candidate.get("seed_units", [])
    )
    if len(seed_nodes) == 2:
        first, second = seed_nodes
        for item in candidate.get("seed_evidence", {}).get("direct_relations", []):
            relation = item.get("relation")
            key = item.get("key")
            if isinstance(relation, str) and isinstance(key, str):
                edges.add((relation, key, first[0], first[1], second[0], second[1]))
    for item in candidate.get("expanded_units", []):
        values = (
            item.get("relation"),
            item.get("key"),
            item.get("from_file_id"),
            item.get("from_unit_id"),
            item.get("file_id"),
            item.get("unit_id"),
        )
        if all(isinstance(value, str) for value in values):
            relation, key, first_file, first_unit, second_file, second_unit = values
            first = (first_file, first_unit)
            second = (second_file, second_unit)
            if second < first:
                first, second = second, first
            edges.add((relation, key, first[0], first[1], second[0], second[1]))
    return frozenset(edges)


def _candidate_relation_signatures(candidate: dict[str, Any]) -> frozenset[tuple[str, str]]:
    return frozenset((edge[0], edge[1]) for edge in _candidate_relation_edges(candidate))


def _candidate_roles(candidate: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        item for item in candidate.get("relation_kinds", [])
        if isinstance(item, str)
    )


def _candidate_fingerprint(candidate: dict[str, Any]) -> str:
    payload = {
        "units": sorted([list(node) for node in _candidate_unit_set(candidate)]),
        "relations": sorted([list(edge) for edge in _candidate_relation_edges(candidate)]),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _seed_provenance(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "seed_units": sorted(
            [item["file_id"], item["unit_id"]]
            for item in candidate.get("seed_units", [])
        ),
        "direct_relations": sorted(
            [item.get("relation", ""), item.get("key", "")]
            for item in candidate.get("seed_evidence", {}).get("direct_relations", [])
        ),
        "signals_hit": sorted(candidate.get("signals_hit", [])),
    }
    seed_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "seed_fingerprint": seed_fingerprint,
        "seed_units": [
            {"file_id": file_id, "unit_id": unit_id}
            for file_id, unit_id in payload["seed_units"]
        ],
        "seed_kind": candidate.get("seed_evidence", {}).get("seed_kind", ""),
        "signals_hit": payload["signals_hit"],
        "score": candidate.get("score", 0.0),
    }


def _collapse_exact_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    groups: dict[frozenset[Node], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        groups[_candidate_unit_set(candidate)].append(candidate)

    collapsed: list[dict[str, Any]] = []
    for units, group in groups.items():
        ranked = sorted(
            group,
            key=lambda item: (
                -float(item.get("score", 0.0)),
                -len(_candidate_roles(item)),
                item.get("candidate_id", ""),
                _seed_provenance(item)["seed_fingerprint"],
            ),
        )
        retained = deepcopy(ranked[0])
        relation_edges = sorted({
            edge
            for candidate in group
            for edge in _candidate_relation_edges(candidate)
        })
        retained["relation_edges"] = [
            {
                "relation": relation,
                "key": key,
                "first_file_id": first_file,
                "first_unit_id": first_unit,
                "second_file_id": second_file,
                "second_unit_id": second_unit,
            }
            for relation, key, first_file, first_unit, second_file, second_unit
            in relation_edges
        ]
        retained["relation_kinds"] = sorted({
            role
            for candidate in group
            for role in _candidate_roles(candidate)
        })
        retained["signals_hit"] = sorted({
            signal
            for candidate in group
            for signal in candidate.get("signals_hit", [])
            if isinstance(signal, str)
        })
        provenance_by_id = {
            item["seed_fingerprint"]: item
            for item in (_seed_provenance(candidate) for candidate in group)
        }
        retained["candidate_fingerprint"] = _candidate_fingerprint(retained)
        retained["compression"] = {
            "policy": "marginal_coverage_v2",
            "source_seed_count": len(provenance_by_id),
            "source_seeds": [provenance_by_id[key] for key in sorted(provenance_by_id)],
            "absorbed_candidates": [],
        }
        collapsed.append(retained)
    collapsed.sort(
        key=lambda item: (
            -float(item.get("score", 0.0)),
            -len(_candidate_roles(item)),
            -len(_candidate_unit_set(item)),
            item.get("candidate_id", ""),
        )
    )
    return collapsed, len(candidates) - len(collapsed)


def _select_top_v1(candidates: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    dedup: dict[tuple[Node, ...], dict[str, Any]] = {}
    for candidate in candidates:
        key = tuple((item["file_id"], item["unit_id"]) for item in candidate["units"])
        current = dedup.get(key)
        if current is None or candidate["score"] > current["score"]:
            dedup[key] = candidate
    ranked = sorted(
        dedup.values(),
        key=lambda item: (
            -item["score"],
            -len(item["relation_kinds"]),
            len(item["units"]),
            item["candidate_id"],
        ),
    )
    limit = int(cfg["top_candidates"])
    selected: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["candidate_id"] not in chosen_ids and len(selected) < limit:
            selected.append(item)
            chosen_ids.add(item["candidate_id"])

    per_relation = int(cfg.get("min_candidates_per_relation", 0))
    relation_kinds = sorted({kind for item in ranked for kind in item["relation_kinds"]})
    for kind in relation_kinds:
        if sum(kind in candidate["relation_kinds"] for candidate in selected) >= per_relation:
            continue
        for item in (candidate for candidate in ranked if kind in candidate["relation_kinds"]):
            add(item)
            if sum(kind in candidate["relation_kinds"] for candidate in selected) >= per_relation:
                break
    minimum_protocol_supported = int(cfg.get("min_protocol_supported_candidates", 0))
    if sum(
        candidate["seed_evidence"]["seed_kind"] == "protocol_supported"
        for candidate in selected
    ) < minimum_protocol_supported:
        for item in (
            candidate for candidate in ranked
            if candidate["seed_evidence"]["seed_kind"] == "protocol_supported"
        ):
            add(item)
            if sum(
                candidate["seed_evidence"]["seed_kind"] == "protocol_supported"
                for candidate in selected
            ) >= minimum_protocol_supported:
                break
    for item in ranked:
        add(item)
    selected.sort(key=lambda item: (
        -item["score"],
        -len(item["relation_kinds"]),
        item["candidate_id"],
    ))
    for rank, candidate in enumerate(selected, 1):
        candidate["rank"] = rank
    return selected


def _jaccard(first: frozenset[Node], second: frozenset[Node]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def _select_coverage_v2(
    candidates: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    overlap_threshold = float(cfg.get("candidate_overlap_jaccard", 0.5))
    if not 0 <= overlap_threshold <= 1:
        raise ValueError("candidate_overlap_jaccard must be between zero and one")
    limit = int(cfg["top_candidates"])
    if limit < 1:
        raise ValueError("top_candidates must be positive")

    collapsed, exact_duplicates = _collapse_exact_candidates(candidates)
    selected: list[dict[str, Any]] = []
    remaining = list(collapsed)
    covered_units: set[Node] = set()
    covered_edges: set[tuple[str, ...]] = set()
    covered_relations: set[tuple[str, str]] = set()
    covered_roles: set[str] = set()
    suppressed_high_overlap: set[str] = set()

    role_weight = float(cfg.get("coverage_role_weight", 8.0))
    relation_weight = float(cfg.get("coverage_relation_weight", 3.0))
    edge_weight = float(cfg.get("coverage_edge_weight", 1.0))
    unit_weight = float(cfg.get("coverage_unit_weight", 0.25))

    while remaining and len(selected) < limit:
        eligible: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
        for candidate in remaining:
            units = _candidate_unit_set(candidate)
            edges = _candidate_relation_edges(candidate)
            relations = _candidate_relation_signatures(candidate)
            roles = _candidate_roles(candidate)
            new_units = units - covered_units
            new_edges = edges - covered_edges
            new_relations = relations - covered_relations
            new_roles = roles - covered_roles
            if not (new_units or new_edges or new_relations or new_roles):
                continue

            maximum_overlap = max(
                (_jaccard(units, _candidate_unit_set(item)) for item in selected),
                default=0.0,
            )
            if (
                maximum_overlap >= overlap_threshold
                and not new_roles
                and not new_relations
            ):
                suppressed_high_overlap.add(candidate["candidate_fingerprint"])
                continue

            coverage_gain = (
                role_weight * len(new_roles)
                + relation_weight * len(new_relations)
                + edge_weight * len(new_edges)
                + unit_weight * len(new_units)
            )
            details = {
                "new_unit_count": len(new_units),
                "new_relation_edge_count": len(new_edges),
                "new_relation_count": len(new_relations),
                "new_role_count": len(new_roles),
                "maximum_selected_jaccard": round(maximum_overlap, 6),
                "coverage_gain": round(coverage_gain, 6),
            }
            order = (
                -coverage_gain,
                -len(new_roles),
                -len(new_relations),
                -len(new_edges),
                -len(new_units),
                -float(candidate.get("score", 0.0)),
                len(units),
                candidate.get("candidate_id", ""),
                candidate["candidate_fingerprint"],
            )
            eligible.append((order, candidate, details))

        if not eligible:
            break
        eligible.sort(key=lambda row: row[0])
        _, chosen, details = eligible[0]
        remaining.remove(chosen)
        chosen["selection"] = {
            "policy": "marginal_coverage_v2",
            "selection_order": len(selected) + 1,
            **details,
        }
        selected.append(chosen)
        covered_units.update(_candidate_unit_set(chosen))
        covered_edges.update(_candidate_relation_edges(chosen))
        covered_relations.update(_candidate_relation_signatures(chosen))
        covered_roles.update(_candidate_roles(chosen))

    selected_fingerprints = {item["candidate_fingerprint"] for item in selected}
    unselected = [
        item for item in collapsed
        if item["candidate_fingerprint"] not in selected_fingerprints
    ]
    absorbed = 0
    absorbed_by: dict[str, dict[str, Any]] = {}
    for candidate in unselected:
        units = _candidate_unit_set(candidate)
        relations = _candidate_relation_signatures(candidate)
        roles = _candidate_roles(candidate)
        representatives = []
        for representative in selected:
            representative_units = _candidate_unit_set(representative)
            jaccard = _jaccard(units, representative_units)
            contained = units < representative_units
            no_unique_protocol = (
                relations <= _candidate_relation_signatures(representative)
                and roles <= _candidate_roles(representative)
            )
            if contained and no_unique_protocol:
                relationship = "contained_without_unique_protocol"
            elif jaccard >= overlap_threshold and no_unique_protocol:
                relationship = "high_overlap_without_unique_protocol"
            else:
                continue
            representatives.append((
                -jaccard,
                len(representative_units - units),
                representative.get("candidate_id", ""),
                representative,
                relationship,
                jaccard,
            ))
        if not representatives:
            continue
        representatives.sort(key=lambda row: row[:3])
        _, _, _, representative, relationship, jaccard = representatives[0]
        representative["compression"]["absorbed_candidates"].append({
            "candidate_fingerprint": candidate["candidate_fingerprint"],
            "candidate_id": candidate.get("candidate_id", ""),
            "relationship": relationship,
            "jaccard": round(jaccard, 6),
            "source_seed_count": candidate["compression"]["source_seed_count"],
            "score": candidate.get("score", 0.0),
        })
        absorbed_by[candidate["candidate_fingerprint"]] = {
            "reason": relationship,
            "representative_candidate_id": representative.get("candidate_id", ""),
            "representative_fingerprint": representative["candidate_fingerprint"],
            "jaccard": round(jaccard, 6),
        }
        absorbed += 1

    for rank, candidate in enumerate(selected, 1):
        candidate["rank"] = rank
        candidate["compression"]["absorbed_candidates"].sort(
            key=lambda item: (
                item["relationship"],
                -item["jaccard"],
                item["candidate_fingerprint"],
            )
        )

    unselected_manifest = []
    for candidate in sorted(unselected, key=lambda item: item["candidate_fingerprint"]):
        fingerprint = candidate["candidate_fingerprint"]
        record = {
            "candidate_id": candidate.get("candidate_id", ""),
            "candidate_fingerprint": fingerprint,
            "source_seed_count": candidate["compression"]["source_seed_count"],
            "score": candidate.get("score", 0.0),
        }
        if fingerprint in absorbed_by:
            record.update(absorbed_by[fingerprint])
        elif fingerprint in suppressed_high_overlap:
            record["reason"] = "high_overlap_without_new_protocol"
        elif (
            _candidate_unit_set(candidate) <= covered_units
            and _candidate_relation_edges(candidate) <= covered_edges
            and _candidate_roles(candidate) <= covered_roles
        ):
            record["reason"] = "covered_across_selected_candidates"
        else:
            record["reason"] = "candidate_limit_reached"
        unselected_manifest.append(record)

    return selected, {
        "selection_policy": "marginal_coverage_v2",
        "generated_candidate_count": len(candidates),
        "exact_candidate_count": len(collapsed),
        "exact_duplicates_merged": exact_duplicates,
        "selected_candidate_count": len(selected),
        "absorbed_candidate_count": absorbed,
        "high_overlap_candidates_suppressed": len(suppressed_high_overlap),
        "unselected_candidate_count": len(unselected),
        "stopped_before_limit": len(selected) < limit,
        "covered_unit_count": len(covered_units),
        "covered_relation_edge_count": len(covered_edges),
        "covered_relation_count": len(covered_relations),
        "covered_role_count": len(covered_roles),
        "unselected_candidates": unselected_manifest,
    }


def recall_candidates(
    sources: list[dict[str, str]],
    signal_evidences: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
    *, backend=None,
) -> dict[str, Any]:
    """Return frozen task-blind candidate packets for one repository."""
    resolved = {**DEFAULT_CFG, **(cfg or {})}
    for key in ("clone", "skeleton"):
        resolved[key] = {**DEFAULT_CFG[key], **((cfg or {}).get(key, {}))}
    profiles = build_profiles(sources, backend=backend)
    relations = _index_relations(profiles, resolved)
    signal_edges = _collect_signal_edges(signal_evidences)
    seeds = _seed_edges(signal_edges, relations, profiles, resolved)
    generated_candidates = [
        _candidate_from_seed(seed, relations, profiles, signal_edges, resolved)
        for seed in seeds
    ]
    selection_policy = resolved.get("selection_policy", "score_topk_v1")
    if selection_policy == "score_topk_v1":
        candidates = _select_top_v1(generated_candidates, resolved)
        selection_stats = {
            "selection_policy": "score_topk_v1",
            "generated_candidate_count": len(generated_candidates),
            "selected_candidate_count": len(candidates),
        }
    elif selection_policy == "marginal_coverage_v2":
        pool_cfg = dict(resolved)
        pool_cfg["top_candidates"] = int(
            resolved.get("candidate_pool_size", resolved["top_candidates"])
        )
        candidate_pool = _select_top_v1(generated_candidates, pool_cfg)
        candidates, selection_stats = _select_coverage_v2(candidate_pool, resolved)
        selection_stats = {
            **selection_stats,
            "precompression_generated_candidate_count": len(generated_candidates),
            "candidate_pool_policy": "score_topk_v1",
            "candidate_pool_count": len(candidate_pool),
        }
    else:
        raise ValueError(f"unsupported protocol candidate selection policy: {selection_policy!r}")
    relation_counts = Counter(
        evidence["relation"]
        for neighbors in relations.values()
        for records in neighbors.values()
        for evidence in records
    )
    return {
        "candidates": candidates,
        "config": resolved,
        "stats": {
            "source_units": len(profiles),
            "signal_edges": len(signal_edges),
            "qualified_seed_edges": len(seeds),
            "frozen_candidates": len(candidates),
            "relation_counts_directed": dict(sorted(relation_counts.items())),
            **selection_stats,
        },
    }

