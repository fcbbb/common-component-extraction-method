"""Fuse per-signal pair evidence into candidate clusters (files), mutually exclusive.

Each signal (S1 clone / S2 skeleton / S3 semantic) reports per-file-pair evidence.
A pair edge survives when any signal passes its configured bar; surviving edges form
a graph over files, connected components of >= 2 files become candidate clusters.
Components are kept small: per-file edges are capped to the strongest 2 neighbors
before union-find, and oversized components are split by dropping the weakest edge.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from component_method.source_scan.units import unit_is_ancestor

# 兼容信号接口的默认值；最终候选生成使用冻结配置中的阈值。
DEFAULT_CFG = {
    "clone": {"min_shared": 40, "min_containment": 0.35, "min_runs": 1},
    "skeleton": {"min_shared": 18, "min_containment": 0.55, "min_runs": 1},
    "semantic": {"min_cosine": 0.88, "or_top_frac": 0.06},
    "top_neighbors": 2,
    "max_cluster": 6,
    # "leaf" keeps the historical method-first behavior.  "coarse" prefers
    # a class unit when both a class and one of its methods are candidates.
    "unit_preference": "coarse",
}


def _passes(signal: str, cfg: dict[str, Any], edge: dict[str, Any]) -> bool:
    c = cfg[signal]
    if signal == "semantic":
        return edge.get("cosine", 0.0) >= c["min_cosine"]
    tokens = edge.get("shared_tokens", 0)
    containment = edge.get("containment", 0.0)
    runs = edge.get("n_runs", 0)
    return (
        tokens >= c["min_shared"]
        and containment >= c["min_containment"]
        and runs >= c["min_runs"]
    )


def _union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = a, b
    while parent[ra] != ra:
        ra = parent[ra]
    while parent[rb] != rb:
        rb = parent[rb]
    if ra != rb:
        parent[rb] = ra


def _root(parent: dict[str, str], a: str) -> str:
    while parent[a] != a:
        a = parent[a]
    return a


def fuse(
    signal_evidences: list[dict[str, Any]],
    file_ids: list[str],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """signal_evidences: output dicts from clone/ast/semantic cluster_evidence()."""
    cfg = cfg or copy.deepcopy(DEFAULT_CFG)
    per_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for ev in signal_evidences:
        signal = ev["signal"]
        for p in ev["pairs"]:
            key = tuple(sorted([p["file_a"], p["file_b"]]))
            if signal == "semantic":
                per_pair[key][signal] = {
                    "cosine": p.get("cosine", 0.0),
                    "shared_tokens": None,
                }
            else:
                per_pair[key][signal] = {
                    "shared_tokens": p["shared_tokens"],
                    "containment": p["containment"],
                    "n_runs": p["n_runs"],
                }
    # Top-frac semantic edges (cosine may be uniform-low when files genuinely differ).
    if "semantic" in {s["signal"] for s in signal_evidences}:
        cosines = sorted(
            (per_pair[k]["semantic"]["cosine"] for k in per_pair if "semantic" in per_pair[k]),
            reverse=True,
        )
        cutoff = (
            cosines[max(0, min(len(cosines) - 1, int(len(cosines) * cfg["semantic"]["or_top_frac"])))]
            if cosines
            else 0.0
        )
    else:
        cutoff = 0.0

    def passes_semantic(cos: float) -> bool:
        if not cosines:
            return False
        return cos >= cfg["semantic"]["min_cosine"] or (cfg["semantic"]["or_top_frac"] > 0 and cos >= cutoff and cos > 0.0)

    edges: list[dict[str, Any]] = []
    for (file_a, file_b), sigs in per_pair.items():
        reasons: dict[str, bool] = {}
        strength: tuple[float, int] = (0.0, 0)
        for signal, s in sigs.items():
            if signal == "semantic":
                ok = passes_semantic(s["cosine"])
                if ok:
                    strength = max(strength, (s["cosine"], 1))
            else:
                ok = _passes(signal, cfg, s)
                if ok:
                    strength = max(strength, (s["containment"], s["shared_tokens"]))
            reasons[signal] = ok
        if not any(reasons.values()):
            continue
        edges.append({
            "file_a": file_a,
            "file_b": file_b,
            "reasons": reasons,
            "strength": strength[0],
            "tokens": max(
                (s["shared_tokens"] for s in sigs.values() if s.get("shared_tokens") is not None),
                default=0,
            ),
            "signals": sigs,
        })
    edges.sort(key=lambda e: (e["strength"], e["tokens"]), reverse=True)

    # Cap per-file degree to the strongest neighbors so unrelated chains do not merge.
    chosen: set[tuple[str, str]] = set()
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        if degree[e["file_a"]] < cfg["top_neighbors"] and degree[e["file_b"]] < cfg["top_neighbors"]:
            chosen.add(tuple(sorted([e["file_a"], e["file_b"]])))
            degree[e["file_a"]] += 1
            degree[e["file_b"]] += 1

    parent = {f: f for f in file_ids}
    for a, b in chosen:
        _union(parent, a, b)
    comps: dict[str, list[str]] = defaultdict(list)
    for f in file_ids:
        comps[_root(parent, f)].append(f)
    groups = [sorted(v) for v in comps.values() if len(v) >= 2]
    groups.sort(key=lambda g: -sum(e["strength"] for e in edges if {e["file_a"], e["file_b"]} <= set(g)))

    # Split oversized components by dropping the weakest edge until all <= max_cluster.
    while any(len(g) > cfg["max_cluster"] for g in groups):
        over = next(g for g in groups if len(g) > cfg["max_cluster"])
        weak = min(
            (e for e in edges if {e["file_a"], e["file_b"]} <= set(over)),
            key=lambda e: (e["strength"], e["tokens"]),
        )
        parent[weak["file_b"]] = weak["file_b"]
        comps = defaultdict(list)
        for f in file_ids:
            comps[_root(parent, f)].append(f)
        groups = [sorted(v) for v in comps.values() if len(v) >= 2]
        groups.sort(key=lambda g: -sum(e["strength"] for e in edges if {e["file_a"], e["file_b"]} <= set(g)))

    candidates = []
    for members in groups:
        member_set = set(members)
        ev_edges = [e for e in edges if {e["file_a"], e["file_b"]} <= member_set]
        reasons_union: set[str] = set()
        for e in ev_edges:
            reasons_union |= {s for s, ok in e["reasons"].items() if ok}
        shared: dict[str, list[dict[str, Any]]] = {}
        for e in ev_edges:
            for sig, v in e["signals"].items():
                shared.setdefault(sig, []).append({
                    "file_a": e["file_a"],
                    "file_b": e["file_b"],
                    **{k: vv for k, vv in v.items() if k != "signals"},
                })
        candidates.append({
            "members": members,
            "n_members": len(members),
            "signals_hit": sorted(reasons_union),
            "evidence": shared,
            "gain": sum(e["tokens"] for e in ev_edges),
        })
    assigned = {f for g in groups for f in g}
    noise = [f for f in file_ids if f not in assigned]
    return {
        "candidates": candidates,
        "noise": noise,
        "edges_total": len(per_pair),
        "edges_kept": len(edges),
        "config": cfg,
    }


def _unit_edge_key(file_a: str, unit_a: str, file_b: str, unit_b: str) -> tuple[tuple[str, str], tuple[str, str]]:
    left, right = (file_a, unit_a), (file_b, unit_b)
    return (left, right) if left < right else (right, left)


def _unit_components(nodes: set[tuple[str, str]], edges: list[dict[str, Any]]) -> list[set[tuple[str, str]]]:
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {node: set() for node in nodes}
    for edge in edges:
        a, b = edge["a"], edge["b"]
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    seen: set[tuple[str, str]] = set()
    components: list[set[tuple[str, str]]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: set[tuple[str, str]] = set()
        while stack:
            node = stack.pop()
            component.add(node)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components


def _unit_record(signal: str, record: dict[str, Any], file_a: str | None = None, file_b: str | None = None) -> tuple[tuple[str, str], tuple[str, str], dict[str, Any]] | None:
    """Normalize one unit-pair record and retain its signal-specific evidence."""
    if signal == "semantic":
        fields = (record.get("file_a"), record.get("unit_a"), record.get("file_b"), record.get("unit_b"))
        if not all(isinstance(value, str) for value in fields):
            return None
        a, b = _unit_edge_key(*fields)  # type: ignore[arg-type]
        return a, b, {"cosine": record.get("cosine", 0.0)}
    if all(isinstance(record.get(key), str) for key in ("file_a", "unit_a", "file_b", "unit_b")):
        fa, ua, fb, ub = record["file_a"], record["unit_a"], record["file_b"], record["unit_b"]
    else:
        return None
    a, b = _unit_edge_key(fa, ua, fb, ub)
    return a, b, {
        "shared_tokens": record.get("shared_tokens", 0),
        "containment": record.get("containment", 0.0),
        "n_runs": record.get("n_runs", 0),
        "tokens_a": record.get("tokens_a", 0),
        "tokens_b": record.get("tokens_b", 0),
    }


def _remove_nested_candidate_units(
    candidates: list[dict[str, Any]],
    unit_preference: str = "leaf",
) -> list[dict[str, Any]]:
    """Resolve nested candidate scopes without making files exclusive.

    Historical ``leaf`` mode removes an ancestor whenever a descendant is
    present anywhere in the candidate set.  ``coarse`` mode does the reverse
    for class/method pairs, retaining the class envelope and removing the
    method candidate.  Module units are intentionally excluded from the
    coarse preference because they represent the non-container module body,
    not the whole file.
    """
    occurrences: list[tuple[int, str, str]] = []
    for index, candidate in enumerate(candidates):
        for unit in candidate.get("units", []):
            file_id = unit.get("file_id")
            unit_id = unit.get("unit_id")
            if isinstance(file_id, str) and isinstance(unit_id, str):
                occurrences.append((index, file_id, unit_id))

    normalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        kept_units = []
        for unit in candidate.get("units", []):
            file_id = unit.get("file_id")
            unit_id = unit.get("unit_id")
            if not isinstance(file_id, str) or not isinstance(unit_id, str):
                continue
            if unit_preference == "coarse":
                if unit_id.startswith("method:"):
                    has_class_ancestor = any(
                        other_file == file_id
                        and (other_index != index or other_unit_id != unit_id)
                        and other_unit_id.startswith("class:")
                        and unit_is_ancestor(other_unit_id, unit_id)
                        for other_index, other_file, other_unit_id in occurrences
                    )
                    if has_class_ancestor:
                        continue
            else:
                has_descendant = any(
                    other_file == file_id
                    and (other_index != index or other_unit_id != unit_id)
                    and unit_is_ancestor(unit_id, other_unit_id)
                    for other_index, other_file, other_unit_id in occurrences
                )
                if has_descendant:
                    continue
            if unit_preference in {"leaf", "coarse"}:
                kept_units.append(unit)
            else:
                raise ValueError(f"Unsupported unit_preference: {unit_preference!r}")

        members = sorted({unit["file_id"] for unit in kept_units})
        if len(members) < 2:
            continue
        item = dict(candidate)
        item["members"] = members
        item["n_members"] = len(members)
        item["units"] = kept_units
        allowed = {(unit["file_id"], unit["unit_id"]) for unit in kept_units}
        evidence = {}
        for signal, records in (candidate.get("evidence") or {}).items():
            filtered = []
            for record in records:
                a = (record.get("file_a"), record.get("unit_a"))
                b = (record.get("file_b"), record.get("unit_b"))
                if a in allowed and b in allowed:
                    filtered.append(record)
            if filtered:
                evidence[signal] = filtered
        item["evidence"] = evidence
        normalized.append(item)
    return normalized


def fuse_units(signal_evidences: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fuse signal evidence on ``(file_id, unit_id)`` vertices.

    A component may therefore contain multiple units from one file, while each
    unit instance is assigned to at most one candidate.  Candidate members stay
    file IDs so the downstream discovery and extraction schema remains stable.
    """
    cfg = cfg or copy.deepcopy(DEFAULT_CFG)
    nodes: set[tuple[str, str]] = set()
    per_edge: dict[tuple[tuple[str, str], tuple[str, str]], dict[str, dict[str, Any]]] = defaultdict(dict)
    for evidence in signal_evidences:
        signal = evidence.get("signal")
        if signal == "semantic":
            for unit in evidence.get("units", []):
                if isinstance(unit, dict) and isinstance(unit.get("file_id"), str) and isinstance(unit.get("unit_id"), str):
                    nodes.add((unit["file_id"], unit["unit_id"]))
            records = evidence.get("pairs", [])
        else:
            for file_id, unit_sizes in evidence.get("unit_tokens", {}).items():
                for unit_id in unit_sizes:
                    nodes.add((file_id, unit_id))
            records = evidence.get("unit_pairs", [])
            if not records:
                records = [record for pair in evidence.get("pairs", []) for record in pair.get("unit_pairs", [])]
        for raw in records:
            normalized = _unit_record(signal, raw)
            if normalized is None:
                continue
            a, b, value = normalized
            nodes.update((a, b))
            per_edge[(a, b)][signal] = value

    semantic_edges = [values["semantic"]["cosine"] for values in per_edge.values() if "semantic" in values]
    semantic_edges.sort(reverse=True)
    semantic_cfg = cfg["semantic"]
    semantic_cutoff = (
        semantic_edges[max(0, min(len(semantic_edges) - 1, int(len(semantic_edges) * semantic_cfg["or_top_frac"]))) ]
        if semantic_edges
        else 0.0
    )

    def semantic_passes(cosine: float) -> bool:
        return bool(semantic_edges) and (
            cosine >= semantic_cfg["min_cosine"]
            or (semantic_cfg["or_top_frac"] > 0 and cosine >= semantic_cutoff and cosine > 0.0)
        )

    edges: list[dict[str, Any]] = []
    for (a, b), values in per_edge.items():
        reasons: dict[str, bool] = {}
        strength: tuple[float, int] = (0.0, 0)
        for signal, value in values.items():
            passed = semantic_passes(value["cosine"]) if signal == "semantic" else _passes(signal, cfg, value)
            reasons[signal] = passed
            if passed:
                score = (value["cosine"], 1) if signal == "semantic" else (value["containment"], value["shared_tokens"])
                strength = max(strength, score)
        if any(reasons.values()):
            edges.append({
                "a": a,
                "b": b,
                "reasons": reasons,
                "strength": strength[0],
                "tokens": max((value.get("shared_tokens") or 0 for value in values.values()), default=0),
                "signals": values,
            })
    edges.sort(key=lambda edge: (edge["strength"], edge["tokens"]), reverse=True)

    chosen: list[dict[str, Any]] = []
    degree: dict[tuple[str, str], int] = defaultdict(int)
    for edge in edges:
        if degree[edge["a"]] < cfg["top_neighbors"] and degree[edge["b"]] < cfg["top_neighbors"]:
            chosen.append(edge)
            degree[edge["a"]] += 1
            degree[edge["b"]] += 1

    while True:
        components = [component for component in _unit_components(nodes, chosen) if len({file_id for file_id, _ in component}) >= 2]
        oversized = next((component for component in components if len({file_id for file_id, _ in component}) > cfg["max_cluster"]), None)
        if oversized is None:
            break
        internal = [edge for edge in chosen if edge["a"] in oversized and edge["b"] in oversized]
        if not internal:
            break
        weakest = min(internal, key=lambda edge: (edge["strength"], edge["tokens"]))
        chosen.remove(weakest)

    components = [component for component in _unit_components(nodes, chosen) if len({file_id for file_id, _ in component}) >= 2]
    components.sort(key=lambda component: -sum(
        edge["strength"] for edge in edges if edge["a"] in component and edge["b"] in component
    ))
    candidates: list[dict[str, Any]] = []
    for component in components:
        members = sorted({file_id for file_id, _ in component})
        component_edges = [edge for edge in edges if edge["a"] in component and edge["b"] in component]
        reasons_union = {signal for edge in component_edges for signal, passed in edge["reasons"].items() if passed}
        shared: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in component_edges:
            for signal, value in edge["signals"].items():
                shared[signal].append({
                    "file_a": edge["a"][0],
                    "unit_a": edge["a"][1],
                    "file_b": edge["b"][0],
                    "unit_b": edge["b"][1],
                    **value,
                })
        units = [
            {"file_id": file_id, "unit_id": unit_id, "kind": unit_id.split(":", 1)[0] if ":" in unit_id else unit_id}
            for file_id, unit_id in sorted(component)
        ]
        candidates.append({
            "members": members,
            "n_members": len(members),
            "units": units,
            "signals_hit": sorted(reasons_union),
            "evidence": dict(shared),
            "gain": sum(edge["tokens"] for edge in component_edges),
        })
    candidates = _remove_nested_candidate_units(candidates, cfg.get("unit_preference", "leaf"))
    assigned_files = {member for candidate in candidates for member in candidate["members"]}
    file_ids = sorted({file_id for file_id, _ in nodes})
    return {
        "candidates": candidates,
        "noise": [file_id for file_id in file_ids if file_id not in assigned_files],
        "edges_total": len(per_edge),
        "edges_kept": len(edges),
        "config": cfg,
    }
