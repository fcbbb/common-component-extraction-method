#!/usr/bin/env python3
"""Freeze the FFSIM V2 candidates as focus/context extraction packets."""

from __future__ import annotations

import json

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json, sha256, unit_key, write_json

from component_method.protocol_candidates import (  # noqa: E402
    ProtocolPacketConfig,
    pack_protocol_candidates,
)


def main() -> None:
    config = load_json(ROOT / "config.json")
    source_path = PROJECT / config["candidate_file"]
    if sha256(source_path) != config["candidate_sha256"]:
        raise RuntimeError("frozen FFSIM V2 candidate file hash changed")
    source = load_json(source_path)
    candidates = source["candidates"]
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    packets = pack_protocol_candidates(
        candidates,
        config=ProtocolPacketConfig(**config["packet_config"]),
    )

    prepared = []
    for packet in packets:
        packet_units = {unit_key(unit): unit for unit in packet["primary_units"]}
        focus_keys: set[tuple[str, str]] = set()
        focus_groups = []
        for candidate_id, rank in zip(
            packet["candidate_ids"], packet["candidate_ranks"], strict=True
        ):
            candidate = by_id[candidate_id]
            group_keys = {unit_key(unit) for unit in candidate["seed_units"]}
            if not group_keys <= set(packet_units):
                raise RuntimeError(f"seed units missing from packet: {candidate_id}")
            focus_keys.update(group_keys)
            focus_groups.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_rank": rank,
                    "focus_units": candidate["seed_units"],
                    "seed_evidence": candidate["seed_evidence"],
                    "candidate_unit_count": len(candidate["units"]),
                    "expanded_unit_count": len(candidate.get("expanded_units", [])),
                }
            )
        context_keys = set(packet_units) - focus_keys
        prepared.append(
            {
                "packet_id": packet["packet_id"],
                "candidate_ids": packet["candidate_ids"],
                "candidate_ranks": packet["candidate_ranks"],
                "focus_groups": focus_groups,
                "focus_units": [packet_units[key] for key in sorted(focus_keys)],
                "context_units": [packet_units[key] for key in sorted(context_keys)],
                "focus_files": sorted({key[0] for key in focus_keys}),
                "context_files": sorted({key[0] for key in context_keys}),
                "visible_files": packet["primary_files"],
                "visible_unit_count": len(packet_units),
                "focus_unit_count": len(focus_keys),
                "context_unit_count": len(context_keys),
            }
        )

    payload = {
        "schema": "ffsim-focus-context-protocol-packets-v1",
        "task_blind": True,
        "task_id": config["task_id"],
        "source": config["candidate_file"],
        "source_sha256": sha256(source_path),
        "candidate_count": len(candidates),
        "packet_config": config["packet_config"],
        "packet_count": len(prepared),
        "packets": prepared,
    }
    output = ROOT / "inputs" / "focus_context_packets.json"
    if output.exists() and load_json(output) != payload:
        raise RuntimeError(f"preserving different frozen input: {output}")
    write_json(output, payload)
    try:
        output_label = str(output.relative_to(PROJECT))
    except ValueError:
        output_label = str(output)
    print(
        json.dumps(
            {
                "output": output_label,
                "candidate_count": len(candidates),
                "packet_count": len(prepared),
                "packets": [
                    {
                        "packet_id": packet["packet_id"],
                        "candidates": len(packet["candidate_ids"]),
                        "focus_units": packet["focus_unit_count"],
                        "context_units": packet["context_unit_count"],
                    }
                    for packet in prepared
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
