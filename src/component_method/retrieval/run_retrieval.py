#!/usr/bin/env python3
"""Run one complete-catalog retrieval attempt over the reviewed FFSIM library."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json
from component_method.runtime_paths import offline_task_root, task_execution_root

config = load_json(ROOT / "config.json")

from component_method.task_execution.adapters.action_protocol import CompatibleActionAgent
from component_method.retrieval import (  # noqa: E402
    RetrievalRequest,
    run_retrieval_agent,
)


def main() -> None:
    if os.environ.get("MODEL_NAME") != config["model"]:
        raise RuntimeError(f"MODEL_NAME must be {config['model']}")
    if os.environ.get("OPENAI_API_BASE", "").rstrip("/") != config["api_base"]:
        raise RuntimeError(f"OPENAI_API_BASE must be {config['api_base']}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required")

    row = load_json(offline_task_root(config["task_id"]) / "task.json")
    library = ROOT / "outputs" / "full_library"
    manifest = load_json(library / "manifest.json")
    if not manifest.get("component_count"):
        raise RuntimeError("reviewed component library is empty")
    attempt_id = os.environ.get("ATTEMPT_ID", config["retrieval_attempt"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", attempt_id):
        raise RuntimeError("ATTEMPT_ID must contain only lowercase letters, digits, _ or -")
    output = ROOT / "attempts" / attempt_id
    result = run_retrieval_agent(
        RetrievalRequest(
            task_id=config["task_id"],
            problem_statement=row["problem_statement"],
            interface=row.get("interface", ""),
            component_library=library,
            output_dir=output,
            image=config["runtime_image"],
        ),
        model_config={
            "model_name": config["model"],
            "model_kwargs": {
                "drop_params": True,
                "temperature": 0.0,
                "api_base": config["api_base"],
            },
            "litellm_model_registry": str(task_execution_root() / "config" / "pricing.json"),
        },
        agent_class=CompatibleActionAgent,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
