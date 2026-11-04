#!/usr/bin/env python3
"""Run one FFSIM Task Agent with the frozen retrieval result and evaluate it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import traceback

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json
from component_method.runtime_paths import task_execution_root

config = load_json(ROOT / "config.json")
os.environ["COMPONENT_METHOD_TASK_ROOT"] = str(ROOT)
RUNTIME_ROOT = task_execution_root()
sys.path[:0] = [
    str(RUNTIME_ROOT / "core"),
    str(RUNTIME_ROOT / "adapters"),
]

import common  # noqa: E402


def main() -> None:
    attempt_id = os.environ.get("TASK_ATTEMPT_ID", config["task_attempt"])
    retrieval_attempt = os.environ.get(
        "RETRIEVAL_ATTEMPT_ID", config["retrieval_attempt"]
    )
    for name, value in (
        ("TASK_ATTEMPT_ID", attempt_id),
        ("RETRIEVAL_ATTEMPT_ID", retrieval_attempt),
    ):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise RuntimeError(f"{name} must contain only lowercase letters, digits, _ or -")

    output = ROOT / "task_attempts" / attempt_id
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"preserving existing task attempt: {output}")
    output.mkdir(parents=True, exist_ok=True)
    common.OUT = output

    import docker  # noqa: E402
    import evaluation  # noqa: E402
    import task  # noqa: E402
    from component_method.library_publish.agent_bundle import (  # noqa: E402
        normalize_repository_id,
        validate_agent_bundle,
    )
    from component_method.retrieval import (  # noqa: E402
        materialize_selected_bundle,
    )

    task_id = config["task_id"]
    official = next(row for row in common.rows() if row["instance_id"] == task_id)
    group = next(group for group in common.groups() if task_id in group["task_ids"])
    source_library = ROOT / "outputs" / "full_library"
    selection = ROOT / "attempts" / retrieval_attempt / "result.json"
    retrieval_metadata = load_json(ROOT / "attempts" / retrieval_attempt / "metadata.json")
    selected = load_json(selection)
    marker = output / "run_manifest.json"
    manifest = {
        "status": "running",
        "started_at": common.now(),
        "task_id": task_id,
        "model": common.MODEL,
        "source_component_count": load_json(source_library / "manifest.json")[
            "component_count"
        ],
        "retrieval_attempt": retrieval_attempt,
        "retrieval": retrieval_metadata,
        "selected_bundle_ids": selected["selected_bundle_ids"],
        "manual_component_selection": False,
        "task_agent_max_runs": 1,
    }
    common.write(marker, manifest)

    try:
        os.environ.update(common.model_env())
        image_id = docker.from_env().images.get(group["runtime_image"]).id
        input_sha256 = common.input_identity()
        common.write(
            output / "prepared.json",
            {
                "input_sha256": input_sha256,
                "official_images": {task_id: image_id},
                "prepared_at": common.now(),
            },
        )
        common.verify_inputs()

        bundle = materialize_selected_bundle(
            source_library,
            selection,
            output / "selected_component_bundle",
            expected_task_id=task_id,
        )
        bundle_manifest_path = bundle / "manifest.json"
        raw_bundle_manifest = load_json(bundle_manifest_path)
        normalized_repository = normalize_repository_id(raw_bundle_manifest["repository"])
        if raw_bundle_manifest["repository"] != normalized_repository:
            raw_bundle_manifest["repository"] = normalized_repository
            common.write(bundle_manifest_path, raw_bundle_manifest)
        bundle_manifest = validate_agent_bundle(
            bundle,
            group["repo"],
            group["extraction_commit"],
        )
        bundle_sha256 = common.digest(common.hashes(bundle))
        common.write(
            output / "bindings" / f"{task_id}.json",
            {
                "base_commit": official["base_commit"],
                "source_commit": group["extraction_commit"],
                "bundle_sha256": bundle_sha256,
                "selection_source": str(selection),
            },
        )
        manifest.update(
            selected_component_count=bundle_manifest["component_count"],
            bundle=str(bundle),
            bundle_sha256=bundle_sha256,
        )
        common.write(marker, manifest)

        sys.argv = [
            "task.py",
            "--task",
            task_id,
            "--arm",
            "components",
            "--image",
            group["runtime_image"],
            "--bundle",
            str(bundle),
        ]
        task.main()
        inference = common.read(output / "tasks" / "components" / task_id / "result.json")
        manifest["task"] = {
            "status": inference["status"],
            "model_calls": inference["model_calls"],
            "reported_cost_usd": inference["reported_cost_usd"],
            "component_usage": inference.get("component_usage", []),
        }
        if not inference.get("patch_available"):
            raise RuntimeError(f"task agent produced no patch: {inference.get('error')}")

        evaluation_result = evaluation.evaluate(
            official,
            inference["patch"],
            output / "tasks" / "components" / task_id / "evaluation",
            bundle,
        )
        manifest.update(
            status="completed",
            evaluation=evaluation_result,
            inputs_unchanged=common.input_identity() == input_sha256,
            bundle_unchanged=common.digest(common.hashes(bundle)) == bundle_sha256,
            finished_at=common.now(),
        )
    except BaseException as error:
        manifest.update(
            status="failed",
            exception=type(error).__name__,
            error=str(error),
            finished_at=common.now(),
        )
        common.write(
            output / "pipeline_error.json",
            {
                "exception": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        raise
    finally:
        manifest["updated_at"] = common.now()
        common.write(marker, manifest)


if __name__ == "__main__":
    main()
