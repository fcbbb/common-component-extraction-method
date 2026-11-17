#!/usr/bin/env python3
"""Prepare per-task roots for the OS-Bench direct DSH baseline.

The regular task runner expects a task root with a ``config.json`` plus an
``outputs/prepared.json`` identity file.  OS-Bench preparation deliberately
keeps those separate from the component task roots, so create the small
direct-baseline roots here without running any agent.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
DEFAULT_WORKSPACE = REPOSITORY / "work" / "osbench"
DEFAULT_OUTPUT = DEFAULT_WORKSPACE / "direct_baseline"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def selected_tasks(workspace: Path, requested: list[str] | None) -> list[dict]:
    rows = read_json(workspace / "tasks.json")["tasks"]
    if not requested:
        return rows
    by_id = {row["instance_id"]: row for row in rows}
    missing = sorted(set(requested) - set(by_id))
    if missing:
        raise RuntimeError(f"unknown OS-Bench task IDs: {missing}")
    return [by_id[task_id] for task_id in requested]


def task_config_path(workspace: Path, instance_id: str) -> Path:
    return workspace / "tasks" / instance_id / "config.json"


def ensure_component_library_stub(workspace: Path, config: dict) -> Path:
    """The direct arm never reads components, but the shared config loader does."""
    root = (
        workspace
        / "offline_artifacts"
        / "tasks"
        / config["task_id"]
        / "component_library"
    )
    manifest = root / "manifest.json"
    if not manifest.is_file():
        write_json(
            manifest,
            {
                "schema": "osbench-direct-source-stub-v1",
                "source_commit": config["source_commit"],
                "component_count": 0,
                "purpose": "direct baseline only; no component library is used",
            },
        )
    return manifest


def input_identity(workspace: Path, direct_root: Path) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "COMPONENT_METHOD_RELEASE_ROOT": str(workspace),
            "COMPONENT_METHOD_TASK_ROOT": str(direct_root),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPOSITORY / "src"),
                    str(REPOSITORY / "src" / "component_method" / "task_execution" / "core"),
                    str(REPOSITORY / "src" / "component_method" / "task_execution" / "adapters"),
                ]
            ),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, common; print(json.dumps(common.input_identity()))",
        ],
        cwd=REPOSITORY,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def prepare_one(
    workspace: Path,
    row: dict,
    output_root: Path,
    *,
    model: str,
    api_base: str,
    use_prepared_image: bool,
) -> dict:
    instance_id = row["instance_id"]
    source_config = read_json(task_config_path(workspace, instance_id))
    config = dict(source_config)
    config["model"] = model
    config["api_base"] = api_base.rstrip("/")
    if use_prepared_image:
        config["runtime_image"] = row["runtime_image"]
    else:
        config["runtime_image"] = row.get("official_image_name", row["runtime_image"])
    config.update(
        {
            "task_attempt": "direct_01",
            "retrieval_attempt": "unused",
            "direct_baseline": True,
        }
    )
    direct_root = (output_root / instance_id).resolve()
    write_json(direct_root / "config.json", config)
    ensure_component_library_stub(workspace, config)

    identity = input_identity(workspace, direct_root)
    import docker  # local import: only needed when preparing a runnable root

    image_id = docker.from_env().images.get(config["runtime_image"]).id
    write_json(
        direct_root / "outputs" / "prepared.json",
        {
            "input_sha256": identity,
            "official_images": {instance_id: image_id},
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "arm": "direct",
        },
    )
    run_script = direct_root / "run_direct.sh"
    node_bin = Path(
        os.environ.get(
            "COMPONENT_DSH_NODE_BIN",
            str(Path.home() / ".nvm" / "versions" / "node" / "v24.9.0" / "bin" / "node"),
        )
    )
    run_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"cd {REPOSITORY}",
                f"export COMPONENT_METHOD_RELEASE_ROOT={workspace}",
                f"export COMPONENT_METHOD_TASK_ROOT={direct_root}",
                f"export COMPONENT_DSH_NODE_BIN={node_bin}",
                "set -a",
                ". ./.env",
                "set +a",
                "export PYTHONPATH=" + os.pathsep.join(
                    [
                        str(REPOSITORY / "src"),
                        str(REPOSITORY / "src" / "component_method" / "task_execution" / "core"),
                        str(REPOSITORY / "src" / "component_method" / "task_execution" / "adapters"),
                    ]
                ),
                ".venv/bin/python src/component_method/task_execution/core/task.py "
                f"--task {instance_id} --arm direct --image {config['runtime_image']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    run_script.chmod(0o755)
    manifest = {
        "schema": "osbench-direct-baseline-v1",
        "instance_id": instance_id,
        "task_root": str(direct_root),
        "model": model,
        "api_base": config["api_base"],
        "image": config["runtime_image"],
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "command": str(run_script),
    }
    write_json(direct_root / "direct_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--task", action="append", help="OS-Bench task ID; repeatable.")
    parser.add_argument(
        "--model",
        default=os.environ.get("MODEL_NAME", ""),
        help="Bare model name for the OpenAI-compatible route (default: MODEL_NAME).",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_API_BASE", ""),
        help="API base URL (default: OPENAI_API_BASE).",
    )
    parser.add_argument(
        "--official-image",
        action="store_true",
        help="Use the official repolaunch/osbench image instead of the prepared image.",
    )
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if not args.model:
        raise RuntimeError("set MODEL_NAME or pass --model")
    if not args.api_base:
        raise RuntimeError("set OPENAI_API_BASE or pass --api-base")
    rows = selected_tasks(workspace, args.task)
    manifests = [
        prepare_one(
            workspace,
            row,
            args.output_root.resolve(),
            model=args.model,
            api_base=args.api_base,
            use_prepared_image=not args.official_image,
        )
        for row in rows
    ]
    write_json(
        args.output_root.resolve() / "direct_manifest.json",
        {
            "schema": "osbench-direct-baseline-index-v1",
            "model": args.model,
            "api_base": args.api_base,
            "tasks": manifests,
        },
    )
    print(json.dumps({"prepared": len(manifests), "output": str(args.output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())