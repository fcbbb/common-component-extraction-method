#!/usr/bin/env python3
"""检查独立发布包的 Python、Docker、任务配置和运行依赖。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from component_method.agent_runtime import (
    BackendSettings,
    create_agent_backend,
    selected_backend_name,
)


TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
RELEASE = REPOSITORY.parent
OFFLINE = RELEASE / "offline_artifacts"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", help="额外检查指定任务的 Docker 镜像。")
    parser.add_argument("--config", type=Path, help="检查多语言配置及其隔离运行时，不依赖历史 20 任务数据。")
    parser.add_argument("--require-model-env", action="store_true")
    args = parser.parse_args()
    if args.config:
        from component_method.languages.preflight import inspect_configuration

        if args.task:
            parser.error("--config and --task cannot be combined")
        if args.require_model_env and not os.environ.get("OPENAI_API_KEY"):
            parser.error("OPENAI_API_KEY is required")
        print(json.dumps(inspect_configuration(read_json(args.config)), ensure_ascii=False, indent=2))
        return 0
    failures = []
    agent_backend = selected_backend_name()

    if sys.version_info < (3, 12):
        failures.append(f"需要 Python 3.12，当前为 {sys.version.split()[0]}")
    packages = [
        "docker",
        "filelock",
        "hnswlib",
        "jinja2",
        "numpy",
        "openai",
        "scipy",
        "sentence_transformers",
        "torch",
        "tqdm",
        "transformers",
        "yaml",
    ]
    for package in packages:
        if importlib.util.find_spec(package) is None:
            failures.append(f"缺少 Python 包：{package}")
    try:
        backend = create_agent_backend(
            BackendSettings(
                api_key=os.environ.get("OPENAI_API_KEY", "preflight-only"),
                base_url=os.environ.get("OPENAI_API_BASE", "preflight-only"),
                repository_root=REPOSITORY,
            ),
            name=agent_backend,
        )
        backend.validate_runtime()
    except (OSError, RuntimeError, ValueError) as error:
        failures.append(f"{agent_backend} Agent runtime 不可用：{error}")
    if not (OFFLINE / "embeddings" / "unit_embeddings.npy").is_file():
        failures.append("缺少离线嵌入矩阵")
    tasks = [path.name for path in (OFFLINE / "tasks").iterdir() if path.is_dir()]
    if len(tasks) != 20:
        failures.append(f"离线任务数应为 20，实际为 {len(tasks)}")
    if args.require_model_env:
        for name in ("OPENAI_API_KEY", "OPENAI_API_BASE"):
            if not os.environ.get(name):
                failures.append(f"缺少环境变量：{name}")

    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        failures.append(f"Docker 不可用：{error}")
    if args.task:
        task_root = OFFLINE / "tasks" / args.task
        if not task_root.is_dir():
            failures.append(f"未知任务：{args.task}")
        else:
            image = read_json(task_root / "task.json")["image_name"]
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                failures.append(f"本机缺少 Docker 镜像：{image}")

    if failures:
        print("预检失败：")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"预检通过：{agent_backend} Agent、发布包、Python 依赖和 Docker 均可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
