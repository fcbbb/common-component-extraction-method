#!/usr/bin/env python3
"""Build an isolated continuation rooted in the untouched first extraction attempt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from component_method.workflow.batch_common import PROJECT, ROOT, load_json, write_json


def symlink_once(link: Path, target: Path) -> None:
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise RuntimeError(f"preserving different symlink: {link}")
        return
    if link.exists():
        raise RuntimeError(f"preserving existing continuation path: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target.resolve(), link, target_is_directory=True)


def prepare(task_id: str, continuation_name: str) -> dict:
    source_root = ROOT / "tasks" / task_id
    if not source_root.is_dir():
        raise RuntimeError(f"unknown task root: {source_root}")
    extraction_root = source_root / "runs" / task_id / "extraction_v1"
    archived_attempt = extraction_root / "failed_attempts" / "attempt_01"
    if archived_attempt.joinpath("summary.json").is_file():
        source_summary = archived_attempt / "summary.json"
        source_attempt = "failed_attempts/attempt_01"
    else:
        source_summary = extraction_root / "summary.json"
        source_attempt = "current"

    summary = load_json(source_summary)
    if not all(
        result.get("status") in {"ok", "invalid_contract"}
        for result in summary.get("results", [])
    ):
        raise RuntimeError("initial extraction contains an execution/runtime failure")

    continuation = source_root / "continuations" / continuation_name
    config = load_json(source_root / "config.json")
    config["continuation_provenance"] = {
        "mode": "first_extraction_attempt_component_level_admission",
        "source_task_root": str(source_root.relative_to(PROJECT)),
        "source_attempt": source_attempt,
        "extraction_model_rerun": False,
    }
    write_json(continuation / "config.json", config)
    write_json(
        continuation / "inputs" / "focus_context_packets.json",
        load_json(source_root / "inputs" / "focus_context_packets.json"),
    )

    destination_extraction = continuation / "runs" / task_id / "extraction_v1"
    write_json(destination_extraction / "summary.json", summary)
    write_json(destination_extraction / "run_manifest.json", summary)

    packet_sources = []
    for packet_id in summary["packet_ids"]:
        archived_packet = archived_attempt / packet_id
        current_packet = extraction_root / "packets" / packet_id
        packet_source = archived_packet if archived_packet.is_dir() else current_packet
        if not packet_source.joinpath("extraction_response.json").is_file():
            raise RuntimeError(f"missing first-attempt packet output: {packet_id}")
        packet_link = destination_extraction / "packets" / packet_id
        symlink_once(packet_link, packet_source)
        packet_sources.append(
            {
                "packet_id": packet_id,
                "source": str(packet_source.relative_to(PROJECT)),
                "archived_failed_packet": packet_source == archived_packet,
            }
        )

    provenance = {
        "schema": "initial-extraction-continuation-v1",
        "task_id": task_id,
        "continuation_root": str(continuation.relative_to(PROJECT)),
        "source_summary": str(source_summary.relative_to(PROJECT)),
        "source_attempt": source_attempt,
        "extraction_model_rerun": False,
        "packet_sources": packet_sources,
    }
    write_json(continuation / "continuation.json", provenance)
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", required=True)
    parser.add_argument("--name", default="initial_admission")
    args = parser.parse_args()
    results = [prepare(task_id, args.name) for task_id in args.task]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
