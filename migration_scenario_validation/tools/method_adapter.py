#!/usr/bin/env python3
"""Adapt migration task packages to the component-method controller contract.

The method kernel resolves every run/task through a controller-owned registry
(``COMPONENT_DSH_RUN_REGISTRY``) and expects each task root to contain
``config.json`` plus an offline ``task.json``.  Migration packages use
``shared/harness/taskmodel`` instead, so this module builds that view in a
separate directory without touching the task package.

What this makes runnable for the method arm:

* the preparation workflow -- ``component_run_stage`` with ``stage=prepare``
  scans the task workspace and writes focus packets, ``stage=build`` extracts
  and freezes components, ``stage=audit`` reviews them, and ``stage=publish``
  publishes a fresh library at ``<task-root>/outputs/full_library`` using the
  same reviewed-component pipeline as the batch method
  (``max_review_repair_rounds`` = 1);
* ``stage=retrieval`` -- it reads ``problem_statement`` and ``interface`` from
  the adapted ``task.json``, validates the selection, and materializes the
  selected bundle at ``COMPONENT_DSH_BUNDLE_DESTINATION``;
* ``stage=catalog`` remains a kernel-side read-only helper and is not exposed
  to the method agent;
* every other kernel stage resolves its run/task instead of failing with
  ``run is not registered``.

A prebuilt library is not linked: the component method arm always builds its
components from the current attempt's workspace, so the extraction cost and the
result stay attributable to the same task.

CLI::

    python3 tools/method_adapter.py \
      --task-root v1/windows_to_kylin/tasks/l1_poco_thread \
      --output-root /tmp/method-adapter-demo --run-id demo \
      --model deepseek-v4.1-flash-1017 --api-base https://example/v1 \
      --runtime-image migration/kylin:sp3-p2
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.harness import taskmodel  # noqa: E402


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _task_id(task: Mapping[str, Any]) -> str:
    return str(task.get("task_id") or task.get("id") or "").strip()


def _repository(task: Mapping[str, Any]) -> str:
    source = task.get("source") or {}
    repo = _text(source.get("repo")) if isinstance(source, dict) else ""
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return repo


def _problem_statement(task: Mapping[str, Any]) -> str:
    parts = [
        _text(task.get("title")),
        _text(task.get("spec")),
    ]
    target = task.get("target") or {}
    if isinstance(target, dict) and target:
        parts.append(
            "Target environment:\n"
            + "\n".join(f"- {key}: {value}" for key, value in target.items())
        )
    gates = task.get("gates") or {}
    if isinstance(gates, dict) and gates:
        lines = []
        for name, value in gates.items():
            # Hidden-test descriptions and API regexes are evaluator-only.
            if name in {"api_removal", "behavior"} or (
                isinstance(value, dict) and "symbol_regex" in value
            ):
                continue
            lines.append(f"- {name}: {value}")
        if lines:
            parts.append("Gates:\n" + "\n".join(lines))
    return "\n\n".join(part for part in parts if part)


def _interface(task: Mapping[str, Any]) -> str:
    # The observable contract is in ``spec``; gate descriptions often name
    # upstream test suites and must not be shown to the model.
    return "Match the observable behavior in the task spec."


def _sanitize_run_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not cleaned or not re.match(r"[A-Za-z0-9]", cleaned):
        cleaned = f"run-{cleaned}" if cleaned else "run"
    return cleaned[:128]


def _runtime_image(task: Mapping[str, Any], images: Mapping[str, str]) -> str:
    scenario = str(task.get("scenario") or "")
    return images.get(scenario) or os.environ.get("MUSA_IMAGE") or ""


def _language(task: Mapping[str, Any]) -> str:
    """Migration source language used by the component extraction backend."""
    scenario = str(task.get("scenario") or "")
    return "python" if scenario == "cuda_to_musa" else "cpp"


PACKET_CONFIG = {
    "excluded_directory_names": [
        ".git",
        ".components",
        ".venv",
        "__pycache__",
        "build",
        "build-release",
        "cmake-build-debug",
        "component_bundle",
        "dist",
        "evaluator",
        "gold",
        "gold_authored",
        "generated",
        "node_modules",
        "test",
        "tests",
        "third_party",
        "upstream_nonconforming",
        "vendor",
        "venv",
    ],
    "excluded_filenames": ["test_*.py", "*_test.py"],
    "max_file_bytes": 1024 * 1024,
    "max_files_per_packet": 8,
    "max_units_per_packet": 200,
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def build_workspace(
    task_roots: Iterable[Path],
    *,
    output_root: Path,
    run_id: str,
    model: str,
    api_base: str,
    runtime_images: Mapping[str, str],
    repository_root: Optional[Path] = None,
    workspaces: Optional[Mapping[str, Path]] = None,
    retrieval_attempt: str = "retrieval_v1",
    task_attempt: str = "task_v1",
    extraction_workers: int = 2,
    review_workers: int = 2,
    agent_timeout: int = 3600,
) -> Dict[str, Any]:
    """Create method task roots and the run registry for migration tasks."""
    if repository_root is not None and str(repository_root / "src") not in sys.path:
        sys.path.insert(0, str(repository_root / "src"))
    from component_method.dsh_registry import (  # noqa: PLC0415
        empty_registry,
        register_run,
        register_task,
        write_registry,
    )

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    tasks_root = output_root / "tasks"
    offline_root = output_root / "offline_tasks"
    tasks_root.mkdir(parents=True, exist_ok=True)
    offline_root.mkdir(parents=True, exist_ok=True)

    run_key = _sanitize_run_id(run_id)
    registry = empty_registry()
    register_run(registry, run_key, output_root, embedding_dir=None)

    entries: Dict[str, Any] = {}
    for task_root in task_roots:
        task_root = Path(task_root).expanduser().resolve()
        task = taskmodel.load_task(task_root)
        task_id = _task_id(task) or task_root.name
        if not task_id:
            raise ValueError(f"task package has no id: {task_root}")

        method_root = tasks_root / task_id
        for name in ("outputs", "attempts", "task_attempts", "inputs"):
            (method_root / name).mkdir(parents=True, exist_ok=True)

        source = task.get("source") or {}
        workspace = task_root / "work"
        if workspaces is not None and task_id in workspaces:
            workspace = Path(workspaces[task_id]).expanduser().resolve()
        # Every component-method stage reads the original source state.  The
        # main agent owns /workspace and may start editing task code while a
        # background stage is still running; freezing a snapshot keeps review
        # citations and grounding checks stable and independent of that race.
        snapshot = method_root / "source_snapshot"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
        if workspace.is_dir():
            shutil.copytree(
                workspace,
                snapshot,
                symlinks=True,
                ignore=shutil.ignore_patterns("component_bundle", ".git"),
            )
        stage_repository = snapshot if snapshot.is_dir() else workspace
        # Migration preparation builds a fresh library from this attempt's
        # workspace.  A prebuilt library is recorded for diagnostics but is not
        # linked as the mutable ``outputs/full_library`` the prep agent writes.
        method_library = method_root / "outputs" / "full_library"
        method_library.mkdir(parents=True, exist_ok=True)
        selection_path = (
            method_root / "attempts" / retrieval_attempt / "submission" / "selection.json"
        )
        coverage_path = selection_path.with_name("coverage.json")
        bundle_destination = workspace / "component_bundle"
        language = _language(task)
        config = {
            "task_id": task_id,
            "repository": _repository(task),
            "source_commit": _text(source.get("commit")) if isinstance(source, dict) else "",
            "repository_root": str(stage_repository),
            "task_workspace": str(workspace),
            "model": model,
            "api_base": api_base.rstrip("/"),
            "runtime_image": _runtime_image(task, runtime_images),
            "retrieval_attempt": retrieval_attempt,
            "task_attempt": task_attempt,
            "max_review_repair_rounds": 1,
            "source_scan_mode": "migration",
            "language": language,
            "backend_id": f"{language}@1",
            "packet_config": dict(PACKET_CONFIG),
            "extraction_workers": max(1, int(extraction_workers)),
            "review_workers": max(1, int(review_workers)),
            "agent_timeout_seconds": max(1, int(agent_timeout)),
            "baseline_experiment": "repository/src/component_method/task_execution/config",
            "focus_context_instructions": "repository/config/prompts/focus_context_instructions.txt",
            "protocol_contract_instructions": "repository/config/prompts/protocol_contract_instructions.txt",
            "protocol_contract_schema": "repository/config/schemas/protocol_contract_schema.json",
            "apply_review_revisions_without_rereview": False,
            "selection_path": str(selection_path),
            "coverage_path": str(coverage_path),
            "bundle_destination": str(bundle_destination),
            "method_library": str(method_library),
            "migration": {
                "scenario": str(task.get("scenario") or ""),
                "task_root": str(task_root),
                "task_id": task_id,
                "level": task.get("level"),
                "gold_kind": task.get("gold_kind"),
            },
        }
        task_doc = {
            "instance_id": task_id,
            "repo": _repository(task),
            "base_commit": config["source_commit"],
            "problem_statement": _problem_statement(task),
            "interface": _interface(task),
            "scenario": str(task.get("scenario") or ""),
            "target": task.get("target") or {},
            "migration_task_root": str(task_root),
            "language": language,
            "component_bundle": str(bundle_destination),
        }
        _write_json(method_root / "config.json", config)
        _write_json(method_root / "task.json", task_doc)
        _write_json(offline_root / task_id / "task.json", task_doc)

        register_task(
            registry,
            run_key,
            task_id,
            method_root,
            repository=stage_repository if stage_repository.is_dir() else None,
        )
        entries[task_id] = {
            "task_root": str(method_root),
            "migration_task_root": str(task_root),
            "repository_root": str(stage_repository),
            "task_workspace": str(workspace),
            "runtime_image": config["runtime_image"],
            "language": language,
            "library": str(method_library),
            "selection_path": str(selection_path),
            "coverage_path": str(coverage_path),
            "bundle_destination": str(bundle_destination),
        }

    # Retries and stage calls such as run_stage(stage=build) only receive
    # run_id.  An attempt maps exactly one task, so make that task the run
    # default.
    if len(entries) == 1:
        register_run(
            registry,
            run_key,
            output_root,
            embedding_dir=None,
            task_id=next(iter(entries)),
        )

    registry_path = write_registry(registry, output_root / "registry.json")
    manifest = {
        "schema": "migration-method-adapter-v2",
        "run_id": run_key,
        "registry": str(registry_path),
        "offline_tasks": str(offline_root),
        "run_root": str(output_root),
        "library": (
            str(tasks_root / next(iter(entries)) / "outputs" / "full_library")
            if entries
            else ""
        ),
        "tasks": entries,
    }
    _write_json(output_root / "adapter.json", manifest)
    return manifest


def load_view(output_root: Path) -> Optional[Dict[str, Any]]:
    path = Path(output_root).expanduser().resolve() / "adapter.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", action="append", required=True)
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", default="migration")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT.parent)
    parser.add_argument("--runtime-image", action="append", default=[],
                        help="scenario=image; may be repeated")
    parser.add_argument("--workspace", action="append", default=[],
                        help="task_id=path; the attempt workspace the stages must "
                             "use instead of the task package's own work/ tree")
    args = parser.parse_args(argv)

    roots: list[Path] = []
    for item in args.task_root:
        path = Path(item)
        roots.append(path if path.is_absolute() else ROOT / path)
    for parent in args.parent:
        path = Path(parent)
        if not path.is_absolute():
            path = ROOT / path
        roots.extend(sorted(p for p in path.iterdir() if (p / "task.yaml").is_file()))

    images = {
        "ipp_to_vsipl": os.environ.get("IPP_IMAGE", "migration/ipp:cpu"),
        "windows_to_kylin": os.environ.get("KYLIN_IMAGE", "migration/kylin:sp3-p2"),
        "cuda_to_musa": os.environ.get("MUSA_IMAGE", "migration/musa:s4000"),
    }
    for item in args.runtime_image:
        scenario, _, image = item.partition("=")
        if not image:
            parser.error(f"--runtime-image must be scenario=image: {item!r}")
        images[scenario] = image

    workspaces: Dict[str, Path] = {}
    for item in args.workspace:
        task_key, _, raw_path = item.partition("=")
        if not task_key or not raw_path:
            parser.error(f"--workspace must be task_id=path: {item!r}")
        path = Path(raw_path).expanduser()
        workspaces[task_key] = path if path.is_absolute() else (ROOT / path)

    manifest = build_workspace(
        roots,
        output_root=args.output_root,
        run_id=args.run_id,
        model=args.model,
        api_base=args.api_base,
        runtime_images=images,
        repository_root=args.repository_root.expanduser().resolve(),
        workspaces=workspaces or None,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())