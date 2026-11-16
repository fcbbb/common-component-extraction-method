"""Allow-listed execution kernel for the DSH method plugins.

The kernel exposes fixed method names only.  It is intentionally not a generic
Python runner: every command is assembled from a fixed module or ``run_stage``
entrypoint and controller-owned run registry paths.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

from component_method.dsh_jobs import start_job, job_cancel, job_status
from component_method.dsh_registry import RegistryError, load_registry, resolve_run

PROJECT = Path(__file__).resolve().parents[2]
RUN_STAGE_MODULE = "component_method.workflow.run_stage"
RUN_BATCH_MODULE = "component_method.workflow.run_batch"

STAGE_TO_RUN_STAGE = {
    "source_scan": "prepare",
    "extract": "extract",
    "curate": "curate",
    "prepare_reviews": "prepare_reviews",
    "review": "review",
    "finalize_review": "finalize_review",
    "publish_library": "publish",
    "retrieval": "retrieval",
    "task": "task",
}

STAGE_OPTIONS = {
    "source_scan": frozenset(),
    "extract": frozenset({"resume", "workers"}),
    "curate": frozenset(),
    "prepare_reviews": frozenset(),
    "review": frozenset({"resume", "workers"}),
    "finalize_review": frozenset(),
    "publish_library": frozenset(),
    "retrieval": frozenset(),
    "task": frozenset(),
    "report": frozenset(),
}


class KernelError(ValueError):
    """A method request is malformed or outside the allowlist."""


def _python() -> str:
    return os.environ.get("COMPONENT_DSH_PYTHON_BIN") or sys.executable


def _job_root() -> Path:
    return Path(
        os.environ.get("COMPONENT_DSH_JOB_ROOT", PROJECT / "work" / "dsh_jobs")
    ).expanduser().resolve()


def _run_root_from_payload(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise KernelError("run_id is required")
    task_id = payload.get("task_id")
    if task_id is not None and not isinstance(task_id, str):
        raise KernelError("task_id must be a string")
    return resolve_run(registry, run_id, task_id)


def _task_ids(payload: Mapping[str, Any]) -> list[str]:
    value = payload.get("tasks", payload.get("task_ids"))
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise KernelError("tasks must be a list of non-empty strings")
    return list(value)


def _contained_run_path(value: Any, run_root: Path, *, field: str) -> Path:
    if value is None:
        return run_root
    if not isinstance(value, str) or not value:
        raise KernelError(f"{field} must be a non-empty string")
    candidate = Path(value).expanduser().resolve()
    root = run_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise KernelError(f"{field} must stay inside the registered run root")
    return candidate


def _stage_command(
    stage: str,
    payload: Mapping[str, Any],
    registry: dict[str, Any],
) -> list[str]:
    if stage == "report":
        resolved = _run_root_from_payload(payload, registry)
        return [_python(), "-m", "component_method.reporting.summarize"]
    resolved = _run_root_from_payload(payload, registry)
    task_root = resolved["task_root"]
    if task_root is None:
        raise KernelError(f"{stage} requires task_id")
    run_stage = STAGE_TO_RUN_STAGE[stage]
    command = [
        _python(),
        "-m",
        RUN_STAGE_MODULE,
        "--task-root",
        str(task_root),
        "--stage",
        run_stage,
    ]
    allowed = STAGE_OPTIONS[stage]
    if "resume" in allowed and payload.get("resume"):
        command.append("--resume")
    if "workers" in allowed and payload.get("workers") is not None:
        workers = payload["workers"]
        if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
            raise KernelError("workers must be a positive integer")
        command.extend(["--workers", str(workers)])
    return command


def _run_stage_command(payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    stage = payload.get("stage")
    if not isinstance(stage, str):
        raise KernelError("stage is required")
    if stage not in STAGE_TO_RUN_STAGE and stage != "report":
        raise KernelError(f"unsupported stage: {stage!r}")
    return _stage_command(stage, payload, registry)


def _signal_prepare_command(payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    resolved = _run_root_from_payload(payload, registry)
    output = _contained_run_path(
        payload.get("output_dir"),
        resolved["run_root"] / "offline_embedding_50tasks_20261024",
        field="output_dir",
    )
    command = [
        _python(),
        "-m",
        "component_method.signal_analysis.prepare_embeddings",
        "--output-dir",
        str(output),
    ]
    for task in _task_ids(payload):
        command.extend(["--task", task])
    return command


def _signal_embed_command(payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    resolved = _run_root_from_payload(payload, registry)
    base = _contained_run_path(
        payload.get("embedding_dir"),
        resolved["run_root"] / "offline_embedding_50tasks_20261024",
        field="embedding_dir",
    )
    command = [
        _python(),
        "-m",
        "component_method.signal_analysis.compute_embeddings",
        "--input",
        str(base / "units.jsonl.gz"),
        "--input-manifest",
        str(base / "input_manifest.json"),
        "--output",
        str(base / "unit_embeddings.npy"),
        "--result-manifest",
        str(base / "embedding_result_manifest.json"),
    ]
    for key, flag in (
        ("device", "--device"),
        ("batch_size", "--batch-size"),
        ("chunk_size", "--chunk-size"),
        ("cpu_fallback_chars", "--cpu-fallback-chars"),
    ):
        if payload.get(key) is not None:
            command.extend([flag, str(payload[key])])
    if payload.get("resume"):
        command.append("--resume")
    return command


def _protocol_build_command(payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    resolved = _run_root_from_payload(payload, registry)
    embedding_dir = _contained_run_path(
        payload.get("embedding_dir"),
        resolved["run_root"] / "offline_embedding_50tasks_20261024",
        field="embedding_dir",
    )
    command = [
        _python(),
        "-m",
        "component_method.protocol_candidates.build_candidates",
        "--embedding-dir",
        str(embedding_dir),
    ]
    for task in _task_ids(payload):
        command.extend(["--task", task])
    if payload.get("resume"):
        command.append("--resume")
    if payload.get("include_reserve"):
        command.append("--include-reserve")
    if payload.get("regenerate_frozen_candidates"):
        command.append("--regenerate-frozen-candidates")
    return command


def _pipeline_command(payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    resolved = _run_root_from_payload(payload, registry)
    command = [_python(), "-m", RUN_BATCH_MODULE, "--stage", "pipeline"]
    for task in _task_ids(payload):
        command.extend(["--task", task])
    if payload.get("resume", True):
        command.append("--resume")
    else:
        command.append("--no-resume")
    for key, flag in (
        ("task_workers", "--task-workers"),
        ("extraction_workers", "--extraction-workers"),
        ("review_workers", "--review-workers"),
    ):
        if payload.get(key) is not None:
            command.extend([flag, str(payload[key])])
    return command


def _ops_command(payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    module = payload.get("module")
    allowed = {
        "prepare_workspace": "tools.prepare_workspace",
        "prepare_osbench": "tools.prepare_osbench",
        "prepare_osbench_direct": "tools.prepare_osbench_direct",
        "run_osbench_direct": "tools.run_osbench_direct",
        "preflight": "tools.preflight",
        "verify_release": "tools.verify_release",
        "refresh_manifests": "tools.refresh_manifests",
        "compare_backend": "tools.compare_python_backend",
        "clean_runtime": "tools.clean_osbench_runtime",
    }
    if module not in allowed:
        raise KernelError(f"unsupported ops module: {module!r}")
    command = [_python(), "-m", allowed[module]]
    args = payload.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise KernelError("args must be a list of strings")
    command.extend(args)
    return command


def _check_submission(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.component_build.submission import load_submission

    output = os.environ.get("COMPONENT_DSH_OUTPUT_HOST_DIR")
    role = os.environ.get("COMPONENT_DSH_SUBMISSION_ROLE")
    if not output:
        raise KernelError("COMPONENT_DSH_OUTPUT_HOST_DIR is not configured")
    if not role:
        raise KernelError("COMPONENT_DSH_SUBMISSION_ROLE is not configured")
    load_submission(Path(output).expanduser().resolve(), role)
    return {"ok": True, "role": role}


def _validate_draft(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.component_build.contracts import (
        normalize_component_draft,
        validate_component_draft,
    )

    value = payload.get("component")
    component_id = payload.get("component_id")
    if not isinstance(value, dict):
        raise KernelError("component must be an object")
    if not isinstance(component_id, str) or not component_id:
        component_id = value.get("component_id")
    if not isinstance(component_id, str) or not component_id:
        raise KernelError("component_id is required")
    draft = normalize_component_draft(
        value,
        component_id=component_id,
        origin_strategy=str(payload.get("origin_strategy", "dsh")),
    )
    diagnostics = validate_component_draft(draft)
    return {"ok": not diagnostics, "diagnostics": diagnostics}


def _validate_artifact(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.languages.contracts import ComponentArtifact
    from component_method.languages.registry import default_registry

    value = payload.get("artifact")
    if not isinstance(value, dict):
        raise KernelError("artifact must be an object")
    artifact = ComponentArtifact.from_json(value)
    backend = default_registry().resolve({"language": artifact.language}).single()
    diagnostics = [item.message for item in backend.validate_artifact(artifact)]
    return {"ok": not diagnostics, "diagnostics": diagnostics}


def _library_path() -> Path:
    value = os.environ.get("COMPONENT_DSH_COMPONENT_LIBRARY")
    if not value:
        raise KernelError("COMPONENT_DSH_COMPONENT_LIBRARY is not configured")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise KernelError(f"component library does not exist: {path}")
    return path


def _catalog(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.retrieval.service import build_component_catalog

    return {"ok": True, "catalog": build_component_catalog(_library_path())}


def _validate_selection(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.retrieval.submission import validate_selection

    selection = os.environ.get("COMPONENT_DSH_SELECTION_PATH")
    coverage = os.environ.get("COMPONENT_DSH_COVERAGE_PATH")
    task_id = os.environ.get("COMPONENT_DSH_TASK_ID")
    if not selection:
        raise KernelError("COMPONENT_DSH_SELECTION_PATH is not configured")
    if not task_id:
        raise KernelError("COMPONENT_DSH_TASK_ID is not configured")
    result = validate_selection(
        _library_path(),
        Path(selection).expanduser().resolve(),
        expected_task_id=task_id,
        coverage_path=Path(coverage).expanduser().resolve() if coverage else None,
    )
    return {"ok": True, "selection": result}


def _materialize_selection(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.retrieval.selection_bundle import materialize_selected_bundle

    selection = os.environ.get("COMPONENT_DSH_SELECTION_PATH")
    destination = os.environ.get("COMPONENT_DSH_BUNDLE_DESTINATION")
    if not selection:
        raise KernelError("COMPONENT_DSH_SELECTION_PATH is not configured")
    if not destination:
        raise KernelError("COMPONENT_DSH_BUNDLE_DESTINATION is not configured")
    result = materialize_selected_bundle(
        _library_path(),
        Path(selection).expanduser().resolve(),
        Path(destination).expanduser().resolve(),
    )
    return {"ok": True, "materialized": result}


def _check_patch(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    patch = os.environ.get("COMPONENT_DSH_PATCH_PATH")
    repository = os.environ.get("COMPONENT_DSH_REPOSITORY")
    if not patch:
        raise KernelError("COMPONENT_DSH_PATCH_PATH is not configured")
    if not repository:
        raise KernelError("COMPONENT_DSH_REPOSITORY is not configured")
    patch_path = Path(patch).expanduser().resolve()
    repository_path = Path(repository).expanduser().resolve()
    if not patch_path.is_file():
        raise KernelError(f"patch does not exist: {patch_path}")
    if not repository_path.is_dir():
        raise KernelError(f"repository does not exist: {repository_path}")
    result = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=str(repository_path),
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _status_job(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise KernelError("job_id is required")
    result = job_status(_job_root(), job_id, log_bytes=int(payload.get("log_bytes", 8000)))
    result["ok"] = result.get("status") != "missing"
    return result


def _cancel_job(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise KernelError("job_id is required")
    result = job_cancel(_job_root(), job_id)
    result["ok"] = result.get("status") != "missing"
    return result


METHODS: dict[str, Callable[[Mapping[str, Any], dict[str, Any]], dict[str, Any]]] = {
    **{
        stage: (lambda payload, registry, stage=stage: _run_command_result(
            stage, _stage_command(stage, payload, registry), payload, registry
        ))
        for stage in ("source_scan", "extract", "curate", "prepare_reviews", "review", "finalize_review", "publish_library", "retrieval", "task", "report")
    },
    "run_stage": lambda payload, registry: _run_command_result(
        "run_stage", _run_stage_command(payload, registry), payload, registry
    ),
    "signal_prepare": lambda payload, registry: _run_command_result(
        "signal_prepare", _signal_prepare_command(payload, registry), payload, registry
    ),
    "signal_embed": lambda payload, registry: _run_command_result(
        "signal_embed", _signal_embed_command(payload, registry), payload, registry
    ),
    "protocol_build": lambda payload, registry: _run_command_result(
        "protocol_build", _protocol_build_command(payload, registry), payload, registry
    ),
    "pipeline": lambda payload, registry: _run_command_result(
        "pipeline", _pipeline_command(payload, registry), payload, registry
    ),
    "ops": lambda payload, registry: _run_command_result(
        "ops", _ops_command(payload, registry), payload, registry
    ),
    "check_submission": _check_submission,
    "validate_draft": _validate_draft,
    "validate_artifact": _validate_artifact,
    "check_patch": _check_patch,
    "catalog": _catalog,
    "validate_selection": _validate_selection,
    "materialize_selection": _materialize_selection,
    "job_status": _status_job,
    "job_cancel": _cancel_job,
}


def _environment(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    resolved = None
    if payload.get("run_id"):
        resolved = _run_root_from_payload(payload, registry)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "PYTHONPATH": ":".join(
            dict.fromkeys([str(PROJECT / "src"), os.environ.get("PYTHONPATH", "")]).keys()
        ).strip(":"),
        "PYTHONUNBUFFERED": "1",
        "COMPONENT_METHOD_RUN_ROOT": str(resolved["run_root"]) if resolved else str(PROJECT / "work"),
        "COMPONENT_METHOD_TASK_ROOT": str(resolved["task_root"]) if resolved and resolved["task_root"] else "",
    }
    for name in (
        "MODEL_NAME",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "COMPONENT_DSH_RUN_REGISTRY",
        "COMPONENT_DSH_JOB_ROOT",
        "COMPONENT_DSH_PYTHON_BIN",
    ):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment


def _run_command_result(
    method: str,
    command: Sequence[str],
    payload: Mapping[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        list(command),
        cwd=str(PROJECT),
        env=_environment(payload, registry),
        capture_output=True,
        text=True,
        timeout=float(payload.get("timeout_seconds", 7200)),
        shell=False,
    )
    return {
        "ok": result.returncode == 0,
        "method": method,
        "exit_code": result.returncode,
        "stdout": result.stdout[-20000:],
        "stderr": result.stderr[-20000:],
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


def execute_method(
    method: str,
    payload: Mapping[str, Any],
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one allow-listed method without a shell."""
    if method not in METHODS:
        raise KernelError(f"unknown method: {method}")
    if not isinstance(payload, dict):
        raise KernelError("payload must be an object")
    selected = registry if registry is not None else load_registry()
    try:
        return METHODS[method](payload, selected)
    except RegistryError as exc:
        return {"ok": False, "method": method, "error": str(exc)}
    except (KernelError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"ok": False, "method": method, "error": f"{type(exc).__name__}: {exc}"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=sorted(METHODS))
    parser.add_argument("--job", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"invalid JSON: {exc}"}))
        return 2
    if not isinstance(payload, dict):
        print(json.dumps({"ok": False, "error": "payload must be an object"}))
        return 2
    if args.job:
        try:
            registry = load_registry()
            if args.method not in METHODS:
                raise KernelError(f"unknown method: {args.method}")
            command = _command_for_job(args.method, payload, registry)
            status = start_job(
                job_root=_job_root(),
                method=args.method,
                command=command,
                cwd=PROJECT,
                environment=_environment(payload, registry),
            )
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
            return 1
        print(json.dumps({"ok": True, "method": args.method, "job_id": status["job_id"], "status": status["status"]}, ensure_ascii=False))
        return 0
    result = execute_method(args.method, payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def _command_for_job(method: str, payload: Mapping[str, Any], registry: dict[str, Any]) -> list[str]:
    if method == "run_stage":
        return _run_stage_command(payload, registry)
    if method in {"source_scan", "extract", "curate", "prepare_reviews", "review", "finalize_review", "publish_library", "retrieval", "task", "report"}:
        return _stage_command(method, payload, registry)
    if method == "signal_prepare":
        return _signal_prepare_command(payload, registry)
    if method == "signal_embed":
        return _signal_embed_command(payload, registry)
    if method == "protocol_build":
        return _protocol_build_command(payload, registry)
    if method == "pipeline":
        return _pipeline_command(payload, registry)
    if method == "ops":
        return _ops_command(payload, registry)
    raise KernelError(f"method does not support job mode: {method}")


if __name__ == "__main__":
    raise SystemExit(main())
