#!/usr/bin/env python3
"""Run task-blind protocol-contract extraction over all frozen FFSIM packets."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import time

from component_method.workflow.experiment_common import (
    PROJECT,
    ROOT,
    load_json,
    sha256,
    validate_protocol_contracts,
    write_json,
)

from component_method.component_build.experiment import (  # noqa: E402
    load_component_contract,
    resolve_prompt,
)
from component_method.component_build.extraction import (  # noqa: E402
    ExtractionRequest,
    extract_components,
)
from component_method.component_build.extraction.runner import (  # noqa: E402
    OfficialImageExtractionRunner,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    config = load_json(ROOT / "config.json")
    if os.environ.get("MODEL_NAME") != config["model"]:
        raise RuntimeError(f"MODEL_NAME must be {config['model']}")
    if os.environ.get("OPENAI_API_BASE", "").rstrip("/") != config["api_base"]:
        raise RuntimeError(f"OPENAI_API_BASE must be {config['api_base']}")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    input_path = ROOT / "inputs" / "focus_context_packets.json"
    payload = load_json(input_path)
    packets = payload["packets"]
    workers = args.workers or config["extraction_workers"]

    baseline = PROJECT / config["baseline_experiment"]
    focus_instructions = PROJECT / config["focus_context_instructions"]
    protocol_instructions = PROJECT / config["protocol_contract_instructions"]
    schema_path = PROJECT / config["protocol_contract_schema"]
    repository_root = PROJECT / config["repository_root"]
    runner = OfficialImageExtractionRunner(
        model=config["model"],
        api_key=api_key,
        base_url=config["api_base"],
        timeout_seconds=config["agent_timeout_seconds"],
        runtime_image=config["runtime_image"],
        repository_root=repository_root,
    )
    system_prompt = "\n\n".join(
        (
            resolve_prompt(baseline, "extraction/extract_system.txt").rstrip(),
            focus_instructions.read_text(encoding="utf-8").strip(),
            protocol_instructions.read_text(encoding="utf-8").strip(),
        )
    )
    contract = load_component_contract(baseline)
    contract["required_fields"] = [*contract["required_fields"], "protocol_contract"]

    run_root = ROOT / "runs" / config["task_id"] / "extraction_v1"
    output_root = run_root / "packets"
    manifest_path = run_root / "run_manifest.json"
    manifest = {
        "schema": "ffsim-protocol-contract-extraction-run-v1",
        "task_blind": True,
        "task_information_used": False,
        "task_id": config["task_id"],
        "packet_count": len(packets),
        "packet_ids": [packet["packet_id"] for packet in packets],
        "workers": workers,
        "model": config["model"],
        "runtime_image": config["runtime_image"],
        "input_sha256": sha256(input_path),
        "baseline_prompt_sha256": sha256(
            baseline / "prompts" / "extraction" / "extract_system.txt"
        ),
        "focus_context_instructions_sha256": sha256(focus_instructions),
        "protocol_contract_instructions_sha256": sha256(protocol_instructions),
        "protocol_contract_schema_sha256": sha256(schema_path),
    }
    if manifest_path.exists():
        existing = load_json(manifest_path)
        for key in ("task_id", "packet_ids", "input_sha256", "model", "runtime_image"):
            if existing.get(key) != manifest[key]:
                raise RuntimeError(f"existing extraction manifest changed at {key}")
        if not args.resume:
            raise RuntimeError("extraction already started; use --resume")
    else:
        write_json(manifest_path, {**manifest, "status": "running"})

    def completed_result(packet: dict) -> dict | None:
        packet_root = output_root / packet["packet_id"]
        result_path = packet_root / "result.json"
        if not result_path.is_file():
            return None
        result = load_json(result_path)
        if result.get("status") != "ok":
            return None
        return result

    def run_packet(packet: dict) -> tuple[str, dict]:
        packet_id = packet["packet_id"]
        previous = completed_result(packet)
        if previous is not None:
            return packet_id, {**previous, "resumed": True}
        packet_root = output_root / packet_id
        if packet_root.exists() and any(packet_root.iterdir()):
            resumable = (
                args.resume
                and (packet_root / "trajectory.json").is_file()
                and (packet_root / "file_submissions").is_dir()
            )
            if not resumable:
                raise RuntimeError(f"incomplete packet output requires cleanup: {packet_root}")
        context = {
            "focus_context_policy": (
                "Every component must contain at least one exact focus_units entry in members; "
                "context-only capabilities must not be independently published."
            ),
            "protocol_contract_policy": (
                "Every published component must provide a task-blind, source-grounded "
                "protocol_contract."
            ),
            "source_packet_id": packet_id,
            "candidate_ids": packet["candidate_ids"],
            "candidate_ranks": packet["candidate_ranks"],
            "focus_groups": packet["focus_groups"],
            "focus_units": packet["focus_units"],
            "context_units": packet["context_units"],
            "visible_files": packet["visible_files"],
        }
        request = ExtractionRequest(
            workspace_root=repository_root,
            output_dir=packet_root,
            strategy="protocol_seed_focus_context_contract_v1",
            workspace_scope="candidate",
            context=context,
            expected_files=packet["visible_files"],
            output_contract=contract,
        )
        started = time.monotonic()
        drafts = extract_components(request, agent_runner=runner, system_prompt=system_prompt)
        response = load_json(packet_root / "extraction_response.json")
        validation = validate_protocol_contracts(
            response,
            packet=packet,
            repository_root=repository_root,
            schema_path=schema_path,
        )
        write_json(packet_root / "protocol_contract_validation.json", validation)
        result = {
            "packet_id": packet_id,
            "status": "ok" if validation["status"] == "ok" else "invalid_contract",
            "candidate_count": len(packet["candidate_ids"]),
            "focus_unit_count": packet["focus_unit_count"],
            "context_unit_count": packet["context_unit_count"],
            "draft_count": len(drafts),
            "component_ids": [draft.component_id for draft in drafts],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "protocol_contract_validation": validation,
        }
        write_json(packet_root / "result.json", result)
        return packet_id, result

    results_by_id = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_packet, packet): packet for packet in packets}
        for completed, future in enumerate(as_completed(futures), 1):
            packet = futures[future]
            packet_id = packet["packet_id"]
            try:
                _, result = future.result()
            except Exception as exc:
                result = {
                    "packet_id": packet_id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                write_json(output_root / packet_id / "result.json", result)
            results_by_id[packet_id] = result
            print(
                json.dumps(
                    {"completed": completed, "total": len(packets), **result},
                    ensure_ascii=False,
                ),
                flush=True,
            )

    results = [results_by_id[packet["packet_id"]] for packet in packets]
    statuses = [load_json(path) for path in output_root.glob("*/agent_status.json")]
    summary = {
        **manifest,
        "status": "completed"
        if all(result["status"] == "ok" for result in results)
        else "failed",
        "successful_packets": sum(result["status"] == "ok" for result in results),
        "failed_packets": sum(result["status"] != "ok" for result in results),
        "component_count": sum(result.get("draft_count", 0) for result in results),
        "results": results,
        "extraction_api_calls": sum(int(status.get("api_calls") or 0) for status in statuses),
        "extraction_reported_cost_usd": round(
            sum(float(status.get("reported_cost_usd") or 0) for status in statuses), 9
        ),
    }
    write_json(run_root / "summary.json", summary)
    write_json(manifest_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed_packets"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
