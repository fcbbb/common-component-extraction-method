#!/usr/bin/env python3
"""从发布包离线材料生成可写的独立运行工作区。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
RELEASE = REPOSITORY.parent
OFFLINE = RELEASE / "offline_artifacts"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_to_release(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(RELEASE.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def task_ids(requested: list[str] | None) -> list[str]:
    configured = [
        row["instance_id"]
        for row in read_json(REPOSITORY / "config" / "release_tasks.json")["tasks"]
    ]
    if not requested:
        return configured
    unknown = sorted(set(requested) - set(configured))
    if unknown:
        raise RuntimeError(f"未知任务：{unknown}")
    return list(dict.fromkeys(requested))


def materialize_source(task: dict, destination: Path, refresh: bool) -> Path:
    if destination.is_dir() and any(destination.iterdir()) and not refresh:
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    container = subprocess.check_output(
        ["docker", "create", task["image_name"], "sleep", "60"], text=True
    ).strip()
    try:
        repository_name = task["repo"].split("/", 1)[1]
        subprocess.run(
            ["docker", "cp", f"{container}:/{repository_name}", str(destination)],
            check=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
    git_root = destination / ".git"
    if git_root.is_dir():
        shutil.rmtree(git_root)
    return destination


def task_config(
    task_id: str,
    api_base: str,
    method: dict,
    candidate: Path,
    repository_root: Path,
) -> dict:
    root = OFFLINE / "tasks" / task_id
    task = read_json(root / "task.json")
    provenance = read_json(root / "provenance.json")
    library = read_json(root / "component_library" / "manifest.json")
    pipeline = method["pipeline"]
    return {
        "schema": "component-method-standalone-task-v1",
        "task_id": task_id,
        "repository": task["repo"],
        "source_commit": library["source_commit"],
        "model": method["task_model"],
        "api_base": api_base,
        "agent_timeout_seconds": pipeline["agent_timeout_seconds"],
        "extraction_workers": pipeline["extraction_workers"],
        "review_workers": pipeline["review_workers"],
        "runtime_image": task["image_name"],
        "candidate_file": relative_to_release(candidate),
        "candidate_sha256": sha256(candidate),
        "repository_root": relative_to_release(repository_root),
        "baseline_experiment": "repository/src/component_method/task_execution/config",
        "focus_context_instructions": "repository/config/prompts/focus_context_instructions.txt",
        "protocol_contract_instructions": "repository/config/prompts/protocol_contract_instructions.txt",
        "protocol_contract_schema": "repository/config/schemas/protocol_contract_schema.json",
        "packet_config": pipeline["packet_config"],
        "max_review_repair_rounds": pipeline["max_review_repair_rounds"],
        "retrieval_attempt": "retrieval_01",
        "task_attempt": "task_01",
        "source_subdir": provenance["source_subdir"],
        "apply_review_revisions_without_rereview": False,
    }


def workspace_config(method: dict, api_base: str) -> dict:
    return {
        "schema": "component-method-standalone-workspace-v1",
        "experiment_id": "component-method-final-20tasks-standalone",
        "frozen_pipeline": "component_method.workflow",
        "model": method["task_model"],
        "api_base": api_base.rstrip("/"),
        "embedding": method["embedding"],
        "pipeline": method["pipeline"],
        "candidate_config": "repository/config/reference/candidate_generation.json",
        "bootstrap_embeddings": "offline_artifacts/embeddings",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", help="仅准备指定任务，可重复。")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=REPOSITORY / "work",
        help="可写运行目录，默认 repository/work。",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_API_BASE", ""),
        help="模型兼容接口地址；默认读取 OPENAI_API_BASE。",
    )
    parser.add_argument("--refresh", action="store_true", help="刷新已生成的配置和候选文件。")
    parser.add_argument(
        "--materialize-sources",
        action="store_true",
        help="从任务 Docker 镜像提取完整源码到工作区，供运行时验证使用。",
    )
    args = parser.parse_args()
    if not args.api_base:
        raise RuntimeError("请设置 OPENAI_API_BASE 或传入 --api-base")

    workspace = args.workspace.resolve()
    method = read_json(REPOSITORY / "config" / "method.json")
    selected = task_ids(args.task)
    rows = []
    for task_id in selected:
        offline_root = OFFLINE / "tasks" / task_id
        task = read_json(offline_root / "task.json")
        provenance = read_json(offline_root / "provenance.json")
        source_candidate = offline_root / "discovery" / "protocol_candidates_v2.json"
        if not source_candidate.is_file():
            raise RuntimeError(f"任务缺少协议候选：{task_id}")
        task_root = workspace / "tasks" / task_id
        candidate = task_root / "candidates" / "protocol_candidates_v2.json"
        if candidate.exists() and not args.refresh:
            if sha256(candidate) != sha256(source_candidate):
                raise RuntimeError(f"已有候选与发布包不同，请使用 --refresh：{candidate}")
        else:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_candidate, candidate)
        repository_root = offline_root / "source_snapshot"
        if args.materialize_sources:
            repository_root = materialize_source(
                task,
                task_root / "repository",
                args.refresh,
            )
        config = task_config(
            task_id,
            args.api_base.rstrip("/"),
            method,
            candidate,
            repository_root,
        )
        for name in ("pipeline_config.template.json", "config.json"):
            write_json(task_root / name, config)
        rows.append(
            {
                "index": len(rows) + 1,
                "instance_id": task_id,
                "cohort": "primary",
                "repo": task["repo"],
                "base_commit": task["base_commit"],
                "source_path": "",
                "source_subdir": provenance["source_subdir"],
                "runtime_image": task["image_name"],
                "repository_root": relative_to_release(repository_root),
                "direct_status": "completed",
                "component_status": "pending",
                "imported_component_source": None,
                "frozen_candidate": relative_to_release(source_candidate),
            }
        )

    write_json(workspace / "config.json", workspace_config(method, args.api_base))
    write_json(workspace / "tasks.json", {"schema": "component-method-task-list-v1", "tasks": rows})
    print(f"已准备独立工作区：{workspace}")
    print(f"任务数：{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
