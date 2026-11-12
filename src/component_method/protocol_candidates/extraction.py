"""Prepare task-blind protocol-recall candidates for component extraction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from component_method.component_build.extraction.service import ExtractionRequest
from component_method.languages.contracts import contained_path


@dataclass(frozen=True)
class ProtocolPacketConfig:
    """Bounds for merging overlapping recall candidates into extraction calls."""

    min_shared_units: int = 2
    min_jaccard: float = 0.05
    max_units: int = 60
    max_files: int = 18

    def validate(self) -> None:
        if self.min_shared_units < 1:
            raise ValueError("min_shared_units must be positive")
        if not 0 <= self.min_jaccard <= 1:
            raise ValueError("min_jaccard must be between zero and one")
        if self.max_units < 2:
            raise ValueError("max_units must be at least two")
        if self.max_files < 2:
            raise ValueError("max_files must be at least two")


def _candidate_units(candidate: dict[str, Any]) -> set[tuple[str, str]]:
    units = candidate.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("each protocol candidate must contain a non-empty units list")
    result: set[tuple[str, str]] = set()
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("protocol candidate units must be objects")
        file_id = unit.get("file_id")
        unit_id = unit.get("unit_id")
        if not isinstance(file_id, str) or not file_id or Path(file_id).is_absolute():
            raise ValueError("protocol candidate file_id must be a relative path")
        if ".." in Path(file_id).parts:
            raise ValueError("protocol candidate file_id cannot leave the repository")
        if not isinstance(unit_id, str) or not unit_id:
            raise ValueError("protocol candidate unit_id must be a non-empty string")
        result.add((file_id, unit_id))
    return result


def _packet_id(candidate_ids: list[str], units: set[tuple[str, str]]) -> str:
    payload = {
        "candidate_ids": candidate_ids,
        "units": sorted([list(unit) for unit in units]),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"protocol_packet_{digest}"


def pack_protocol_candidates(
    candidates: Iterable[dict[str, Any]],
    *,
    config: ProtocolPacketConfig | None = None,
) -> list[dict[str, Any]]:
    """Greedily merge overlapping candidates while preserving full unit coverage.

    Candidate order is treated as the frozen recall ranking.  Only source-unit
    overlap and fixed size limits affect packing; task text and audit targets are
    intentionally not accepted by this interface.
    """

    cfg = config or ProtocolPacketConfig()
    cfg.validate()
    packets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for rank, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise ValueError("protocol candidates must be objects")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("each protocol candidate needs a candidate_id")
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate protocol candidate_id: {candidate_id}")
        seen_ids.add(candidate_id)
        units = _candidate_units(candidate)
        identity = {key: candidate[key] for key in ("language", "backend_id") if key in candidate}
        if identity and len(identity) != 2:
            raise ValueError("candidate language and backend_id must be declared together")
        files = {file_id for file_id, _ in units}

        best: tuple[tuple[float, int, int, int], int] | None = None
        for index, packet in enumerate(packets):
            if {key: packet[key] for key in ("language", "backend_id") if key in packet} != identity:
                continue
            packet_units: set[tuple[str, str]] = packet["_units"]
            shared = len(units & packet_units)
            merged_units = units | packet_units
            merged_files = files | packet["_files"]
            jaccard = shared / len(merged_units)
            if (
                shared < cfg.min_shared_units
                or jaccard < cfg.min_jaccard
                or len(merged_units) > cfg.max_units
                or len(merged_files) > cfg.max_files
            ):
                continue
            score = (jaccard, shared, -len(merged_units), -index)
            if best is None or score > best[0]:
                best = (score, index)

        if best is None:
            packets.append({
                **identity,
                "_units": set(units),
                "_files": set(files),
                "candidate_ids": [candidate_id],
                "candidate_ranks": [rank],
            })
            continue

        packet = packets[best[1]]
        packet["_units"].update(units)
        packet["_files"].update(files)
        packet["candidate_ids"].append(candidate_id)
        packet["candidate_ranks"].append(rank)

    result: list[dict[str, Any]] = []
    for packet in packets:
        units = packet.pop("_units")
        files = packet.pop("_files")
        candidate_ids = packet["candidate_ids"]
        result.append({
            **{key: packet[key] for key in ("language", "backend_id") if key in packet},
            "packet_id": _packet_id(candidate_ids, units),
            "candidate_ids": candidate_ids,
            "candidate_ranks": packet["candidate_ranks"],
            "primary_files": sorted(files),
            "primary_units": [
                {"file_id": file_id, "unit_id": unit_id,
                 **({"unit_key": unit_id, "language": packet["language"], "backend_id": packet["backend_id"]}
                    if "language" in packet else {})}
                for file_id, unit_id in sorted(units)
            ],
            "candidate_count": len(candidate_ids),
            "unit_count": len(units),
            "file_count": len(files),
        })
    return result


def protocol_packet_extraction_request(
    *,
    repository_root: Path,
    output_root: Path,
    packet: dict[str, Any],
    output_contract: dict[str, list[str]] | None = None,
    backend=None,
) -> ExtractionRequest:
    """Build an extraction request that exposes only neutral source focus data."""

    packet_id = packet.get("packet_id")
    primary_files = packet.get("primary_files")
    primary_units = packet.get("primary_units")
    if not isinstance(packet_id, str) or not packet_id:
        raise ValueError("protocol packet needs packet_id")
    if not isinstance(primary_files, list) or not all(
        isinstance(item, str) for item in primary_files
    ):
        raise ValueError("protocol packet primary_files must be a list of paths")
    if not isinstance(primary_units, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("file_id"), str)
        and isinstance(item.get("unit_id"), str)
        for item in primary_units
    ):
        raise ValueError("protocol packet primary_units must be source unit objects")
    language_context = {key: packet[key] for key in ("language", "backend_id") if key in packet}
    if language_context:
        if backend is None:
            from component_method.languages.registry import default_registry

            backend = default_registry().resolve({"language": packet["language"]}).single()
        if hasattr(backend, "set_repository"):
            backend.set_repository(repository_root)
        language_context["source_units"] = [
            {key: value for key, value in unit.to_json().items() if key != "metadata"}
            for file_id in primary_files for unit in backend.extract_units(
                file_id, contained_path(repository_root, file_id).read_text())
        ]
        language_context["backend_identity"] = backend.identity().to_json()
    return ExtractionRequest(
        workspace_root=repository_root,
        output_dir=contained_path(output_root, packet_id),
        strategy="protocol_candidate_blind_extraction_v1",
        workspace_scope="candidate",
        context={
            **language_context,
            "primary_extraction_files": list(primary_files),
            "primary_extraction_units": list(primary_units),
        },
        expected_files=list(primary_files),
        output_contract=output_contract or {},
    )

