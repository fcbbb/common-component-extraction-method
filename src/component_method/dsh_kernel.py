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
STAGE_LOCK_MODULE = "component_method.workflow.stage_lock"

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

# Stages that are plain in-process Python calls rather than workflow
# subprocesses.  They are reachable through the single ``run_stage`` entry so
# the model sees one tool instead of one tool per step.
IN_PROCESS_STAGES = frozenset({"catalog", "validate_selection", "materialize_selection"})

DEFAULT_EMBEDDING_DIR = "offline_embedding_50tasks_20261024"

# Operator tool arguments are allow-listed per module.  Values are never
# interpreted by the kernel; each entry says whether the flag takes one value.
OPS_ARGUMENTS: dict[str, dict[str, bool]] = {
    "prepare_workspace": {
        "--task": True,
        "--workspace": True,
        "--api-base": True,
        "--refresh": False,
        "--materialize-sources": False,
    },
    "preflight": {
        "--task": True,
        "--config": True,
        "--require-model-env": False,
    },
    "verify_release": {"--skip-hashes": False},
    "refresh_manifests": {},
    "compare_backend": {"--revision": True},
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


def _embedding_base(resolved: Mapping[str, Any]) -> Path:
    """Resolve the run's embedding directory from registry metadata.

    Runs may declare ``embedding_dir`` (relative to the run root or an absolute
    path inside it); otherwise the historical offline task-set name applies.
    """
    run = resolved.get("run") or {}
    configured = run.get("embedding_dir") or DEFAULT_EMBEDDING_DIR
    if not isinstance(configured, str) or not configured:
        raise KernelError("run embedding_dir must be a non-empty string")
    candidate = Path(configured).expanduser()
    root = resolved["run_root"].resolve()
    if candidate.is_absolute():
        candidate = candidate.resolve()
        if candidate != root and root not in candidate.parents:
            raise KernelError("run embedding_dir must stay inside the registered run root")
        return candidate
    return (root / candidate).resolve()


def _repository_from_environment() -> Path | None:
    value = os.environ.get("COMPONENT_DSH_REPOSITORY")
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise KernelError(f"repository does not exist: {path}")
    return path


def _validated_ops_args(module: str, args: Any) -> list[str]:
    allowed = OPS_ARGUMENTS[module]
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise KernelError("args must be a list of strings")
    validated: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if not token.startswith("--"):
            raise KernelError(f"ops module {module} accepts flags only, not {token!r}")
        name, separator, inline = token.partition("=")
        if name not in allowed:
            raise KernelError(f"ops module {module} does not accept {name}")
        takes_value = allowed[name]
        if separator:
            if not takes_value:
                raise KernelError(f"ops module {module} flag takes no value: {name}")
            if not inline:
                raise KernelError(f"ops module {module} flag needs a value: {name}")
            validated.append(token)
            index += 1
            continue
        if takes_value:
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise KernelError(f"ops module {module} flag needs a value: {name}")
            validated.extend([name, args[index + 1]])
            index += 2
        else:
            validated.append(name)
            index += 1
    return validated


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
        _embedding_base(resolved),
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
        _embedding_base(resolved),
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
        _embedding_base(resolved),
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
        "preflight": "tools.preflight",
        "verify_release": "tools.verify_release",
        "refresh_manifests": "tools.refresh_manifests",
        "compare_backend": "tools.compare_python_backend",
    }
    if module not in allowed:
        raise KernelError(f"unsupported ops module: {module!r}")
    command = [_python(), "-m", allowed[module]]
    command.extend(_validated_ops_args(module, payload.get("args", [])))
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
    diagnostics = validate_component_draft(
        draft, repository=_repository_from_environment()
    )
    return {"ok": not diagnostics, "diagnostics": diagnostics}


def _validate_artifact(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.languages.contracts import ComponentArtifact
    from component_method.languages.registry import default_registry

    value = payload.get("artifact")
    if not isinstance(value, dict):
        raise KernelError("artifact must be an object")
    artifact = ComponentArtifact.from_json(value)
    backend = default_registry().resolve({"language": artifact.language}).single()
    repository = _repository_from_environment()
    if repository is not None and hasattr(backend, "set_repository"):
        backend.set_repository(repository)
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


def _stage_name(method: str, payload: Mapping[str, Any]) -> str | None:
    """The stage the caller asked for, for the one-entry ``run_stage`` tool."""
    requested = payload.get("stage")
    if method == "run_stage" and isinstance(requested, str):
        return requested
    return None


def _envelope(
    *,
    method: str,
    status: str,
    summary: Any = None,
    artifacts: Any = None,
    error_code: str | None = None,
    error: str | None = None,
    stage: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """The single result sheet every method tool returns.

    Synchronous stages, background jobs, and failures all report the same four
    fields, so the workflow prompt never has to switch parsers.
    """
    response: dict[str, Any] = {
        "ok": status == "succeeded",
        "status": status,
        "method": method,
        "summary": summary if isinstance(summary, dict) else {},
        "artifacts": artifacts if isinstance(artifacts, dict) else {},
        "error_code": error_code,
    }
    if stage is not None:
        response["stage"] = stage
    if error:
        response["error"] = error
    response.update(extra)
    return response


def _error_code_for(exc: BaseException) -> str:
    """Map a Python exception onto the stable codes the prompt documents."""
    if isinstance(exc, FileNotFoundError):
        return "STAGE_INPUT_MISSING"
    if isinstance(exc, KernelError):
        message = str(exc)
        if "not configured" in message or "does not exist" in message or "requires" in message:
            return "STAGE_INPUT_MISSING"
        return "BAD_REQUEST"
    return "STAGE_FAILED"


def _failure(
    method: str,
    error_code: str,
    error: str,
    *,
    stage: str | None = None,
    status: str = "failed",
    **extra: Any,
) -> dict[str, Any]:
    return _envelope(
        method=method,
        status=status,
        error_code=error_code,
        error=error,
        stage=stage,
        **extra,
    )


def _catalog(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.retrieval.service import build_component_catalog

    return _envelope(
        method="catalog",
        status="succeeded",
        summary=build_component_catalog(_library_path()),
    )


def _validate_selection(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    from component_method.retrieval.submission import validate_selection

    selection = os.environ.get("COMPONENT_DSH_SELECTION_PATH")
    coverage = os.environ.get("COMPONENT_DSH_COVERAGE_PATH")
    task_id = os.environ.get("COMPONENT_DSH_TASK_ID")
    if not selection:
        raise KernelError("COMPONENT_DSH_SELECTION_PATH is not configured")
    if not task_id:
        raise KernelError("COMPONENT_DSH_TASK_ID is not configured")
    selection_path = Path(selection).expanduser().resolve()
    result = validate_selection(
        _library_path(),
        selection_path,
        expected_task_id=task_id,
        coverage_path=Path(coverage).expanduser().resolve() if coverage else None,
    )
    return _envelope(
        method="validate_selection",
        status="succeeded",
        summary=result,
        artifacts={"selection": str(selection_path)},
    )


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
    # ``materialize_selected_bundle`` returns a Path; the kernel answers in
    # JSON, so the bundle location has to become text here.
    bundle = str(result)
    manifest = _json_if_file(Path(bundle) / "manifest.json") or {}
    return _envelope(
        method="materialize_selection",
        status="succeeded",
        summary={
            "bundle": bundle,
            "component_count": manifest.get("component_count"),
        },
        artifacts={"bundle": bundle, "manifest": str(Path(bundle) / "manifest.json")},
    )


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
    result.setdefault("summary", {})
    result.setdefault("artifacts", {})
    state = result.get("status")
    if state == "missing":
        result["ok"] = False
        result["error_code"] = "JOB_MISSING"
        return result
    if state in {"failed", "cancelled"}:
        result["ok"] = False
        result["error_code"] = "STAGE_FAILED" if state == "failed" else "STAGE_CANCELLED"
        result["error"] = (
            result.get("error")
            or f"job {job_id} finished with status {state}"
        )
    else:
        result["ok"] = True

    # Jobs outlive the kernel process, so their stage summary must be read from
    # the task root recorded when the job started rather than from stdout.
    context = result.get("context") or {}
    task_root = context.get("task_root")
    if task_root and state in {"succeeded", "failed"}:
        try:
            resolved = {
                "run_root": context.get("run_root") or task_root,
                "task_root": Path(task_root),
                "task_id": context.get("task_id"),
            }
            summary = _stage_summary(str(result.get("method") or ""), payload, resolved)
            artifacts = _stage_artifacts(str(result.get("method") or ""), payload, resolved)
            if summary:
                result["summary"] = summary
            if artifacts:
                result["artifacts"] = artifacts
        except (OSError, ValueError):
            pass
    result.setdefault("error_code", None)
    return result


def _cancel_job(payload: Mapping[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise KernelError("job_id is required")
    result = job_cancel(_job_root(), job_id)
    result["ok"] = result.get("status") != "missing"
    result["error_code"] = None if result["ok"] else "JOB_MISSING"
    result.setdefault("summary", {})
    result.setdefault("artifacts", {})
    return result


def _dispatch_run_stage(
    payload: Mapping[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    """The single stage entry: subprocess stages and in-process stages."""
    stage = payload.get("stage")
    if isinstance(stage, str) and stage in IN_PROCESS_STAGES:
        return _in_process_stage(stage, payload, registry)
    return _run_command_result(
        "run_stage", _run_stage_command(payload, registry), payload, registry
    )


METHODS: dict[str, Callable[[Mapping[str, Any], dict[str, Any]], dict[str, Any]]] = {
    **{
        stage: (lambda payload, registry, stage=stage: _run_command_result(
            stage, _stage_command(stage, payload, registry), payload, registry
        ))
        for stage in ("source_scan", "extract", "curate", "prepare_reviews", "review", "finalize_review", "publish_library", "retrieval", "task", "report")
    },
    "run_stage": _dispatch_run_stage,
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
        # Stage agents build their own model route in this subprocess.  Without
        # the budget variables they fall back to the runner defaults (16k
        # output), and a long source-grounded reasoning turn ends on
        # `max-tokens` before the agent writes its submission.
        "COMPONENT_DSH_MAX_OUTPUT_TOKENS",
        "COMPONENT_DSH_CONTEXT_WINDOW",
        "COMPONENT_DSH_RUN_REGISTRY",
        "COMPONENT_DSH_JOB_ROOT",
        "COMPONENT_DSH_PYTHON_BIN",
        "COMPONENT_DSH_OFFLINE_TASKS",
        "COMPONENT_METHOD_OFFLINE_TASKS",
        "COMPONENT_DSH_COMPONENT_LIBRARY",
        "COMPONENT_DSH_SELECTION_PATH",
        "COMPONENT_DSH_COVERAGE_PATH",
        "COMPONENT_DSH_BUNDLE_DESTINATION",
        "COMPONENT_DSH_STAGE_RUNTIME",
        "DOCKER_HOST",
    ):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment


STAGE_METHODS = frozenset(
    {
        "source_scan",
        "extract",
        "curate",
        "prepare_reviews",
        "review",
        "finalize_review",
        "publish_library",
        "retrieval",
        "task",
        "run_stage",
    }
)

# The migration workspace runs the same extraction/review/publish pipeline as
# the batch method: extraction, curation and the component review loop all run
# inside the method task root.  Task execution and reporting must not run there
# because the migration itself happens in the main agent's session.
MIGRATION_UNSUPPORTED_STAGES = frozenset({"task", "report"})


def _task_config(resolved: Mapping[str, Any]) -> dict[str, Any]:
    task_root = resolved.get("task_root")
    if task_root is None:
        return {}
    path = Path(task_root) / "config.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_if_file(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _effective_stage(method: str, payload: Mapping[str, Any]) -> str:
    if method == "run_stage":
        requested = payload.get("stage")
        if isinstance(requested, str):
            return requested
    return method


def _stage_prerequisite(method: str, payload: Mapping[str, Any], resolved: Mapping[str, Any]) -> str | None:
    """Return a stable error code when a stage would run before its inputs exist."""
    method = _effective_stage(method, payload)
    task_root = Path(resolved["task_root"]) if resolved.get("task_root") else None
    if task_root is None:
        return "STAGE_INPUT_MISSING"
    config = _task_config(resolved)
    if (
        config.get("source_scan_mode") == "migration"
        and method in MIGRATION_UNSUPPORTED_STAGES
    ):
        return "STAGE_UNSUPPORTED"
    extraction_root = task_root / "runs" / str(config.get("task_id", "")) / "extraction_v1"
    checks: dict[str, Path] = {
        "extract": task_root / "inputs" / "focus_context_packets.json",
        "curate": extraction_root / "summary.json",
        "prepare_reviews": extraction_root / "curated" / "summary.json",
        "review": task_root / "inputs" / "frozen_components.json",
        "finalize_review": task_root / "runs" / str(config.get("task_id", "")) / "review_v1" / "summary.json",
        "retrieval": task_root / "outputs" / "full_library" / "manifest.json",
    }
    if method == "publish_library":
        if config.get("publish_mode") == "migration_direct":
            checks[method] = extraction_root / "curated" / "summary.json"
        else:
            checks[method] = task_root / "runs" / str(config.get("task_id", "")) / "review_v1" / "summary.json"
    path = checks.get(method)
    if path is not None and not path.is_file():
        return "STAGE_INPUT_MISSING"
    return None


def _stage_summary(method: str, payload: Mapping[str, Any], resolved: Mapping[str, Any]) -> dict[str, Any]:
    """Read the stage's own manifest instead of making the caller parse stdout."""
    method = _effective_stage(method, payload)
    task_root = Path(resolved["task_root"]) if resolved.get("task_root") else None
    if task_root is None:
        return {}
    config = _task_config(resolved)
    task_id = str(config.get("task_id", ""))
    try:
        if method == "source_scan":
            packets = _json_if_file(task_root / "inputs" / "focus_context_packets.json")
            if packets:
                return {
                    "packet_count": packets.get("packet_count"),
                    "source_file_count": packets.get("source_file_count"),
                    "source_unit_count": packets.get("source_unit_count"),
                    "language": packets.get("language"),
                    "gaps": len(packets.get("gaps") or []),
                }
        if method == "extract":
            summary = _json_if_file(task_root / "runs" / task_id / "extraction_v1" / "summary.json")
            if summary:
                return {
                    key: summary.get(key)
                    for key in (
                        "status",
                        "packet_count",
                        "successful_packets",
                        "invalid_packets",
                        "failed_packets",
                        "component_count",
                        "extraction_api_calls",
                        "extraction_input_tokens",
                        "extraction_output_tokens",
                        "extraction_reported_cost_usd",
                    )
                }
        if method == "curate":
            summary = _json_if_file(task_root / "runs" / task_id / "extraction_v1" / "curated" / "summary.json")
            if summary:
                return {
                    key: summary.get(key)
                    for key in ("status", "retained_component_count", "excluded_packet_count")
                }
        if method == "prepare_reviews":
            frozen = _json_if_file(task_root / "inputs" / "frozen_components.json")
            if frozen:
                return {
                    "component_count": frozen.get("component_count"),
                    "component_ids": frozen.get("component_ids"),
                }
        if method == "review":
            summary = _json_if_file(task_root / "runs" / task_id / "review_v1" / "summary.json")
            if summary:
                return {
                    key: summary.get(key)
                    for key in (
                        "status",
                        "successful_components",
                        "failed_components",
                        "published_components",
                        "withheld_components",
                        "max_repair_rounds",
                        "review_api_calls",
                        "review_reported_cost_usd",
                    )
                }
        if method == "publish_library":
            manifest = _json_if_file(task_root / "outputs" / "full_library" / "manifest.json")
            if manifest:
                return {
                    "component_count": manifest.get("component_count"),
                    "schema_version": manifest.get("schema_version"),
                    "library": str(task_root / "outputs" / "full_library"),
                }
        if method == "retrieval":
            attempt = str(config.get("retrieval_attempt") or "retrieval_v1")
            result = _json_if_file(task_root / "attempts" / attempt / "result.json")
            if result:
                return {
                    "selected_bundle_ids": result.get("selected_bundle_ids"),
                    "coverage_file": str(task_root / "attempts" / attempt / "submission" / "coverage.json"),
                }
    except (OSError, ValueError):
        return {}
    return {}


def _stage_artifacts(method: str, payload: Mapping[str, Any], resolved: Mapping[str, Any]) -> dict[str, str]:
    method = _effective_stage(method, payload)
    task_root = Path(resolved["task_root"]) if resolved.get("task_root") else None
    if task_root is None:
        return {}
    config = _task_config(resolved)
    task_id = str(config.get("task_id", ""))
    candidates = {
        "source_scan": task_root / "inputs" / "focus_context_packets.json",
        "extract": task_root / "runs" / task_id / "extraction_v1" / "summary.json",
        "curate": task_root / "runs" / task_id / "extraction_v1" / "curated" / "summary.json",
        "prepare_reviews": task_root / "inputs" / "frozen_components.json",
        "review": task_root / "runs" / task_id / "review_v1" / "summary.json",
        "publish_library": task_root / "outputs" / "full_library" / "manifest.json",
        "retrieval": task_root / "attempts" / str(config.get("retrieval_attempt") or "retrieval_v1") / "result.json",
    }
    path = candidates.get(method)
    return {"manifest": str(path)} if path is not None and path.is_file() else {}


def _try_stage_lock(run_root: Path):
    """Take the run's stage lock without waiting; two stages must not race."""
    path = run_root / ".dsh_stage.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        return None
    return handle


def _release_stage_lock(handle) -> None:
    try:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _run_command_result(
    method: str,
    command: Sequence[str],
    payload: Mapping[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()
    stage = _stage_name(method, payload)
    resolved: dict[str, Any] | None = None
    lock = None
    if method in STAGE_METHODS and payload.get("run_id"):
        resolved = _run_root_from_payload(payload, registry)
        error_code = _stage_prerequisite(method, payload, resolved)
        if error_code is not None:
            return _failure(
                method,
                error_code,
                (
                    "this stage is not available in a migration workspace; "
                    "follow the fixed migration workflow"
                    if error_code == "STAGE_UNSUPPORTED"
                    else "required stage input is missing; run the preceding stage first"
                ),
                stage=stage,
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
        # Lock per task when the run has task roots, so separate migration tasks
        # can still run concurrently; otherwise the whole run shares one lock.
        lock_root = Path(resolved["task_root"] or resolved["run_root"])
        lock = _try_stage_lock(lock_root)
        if lock is None:
            return _failure(
                method,
                "STAGE_BUSY",
                "another component-method stage is already running in this run",
                stage=stage,
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
    try:
        result = subprocess.run(
            list(command),
            cwd=str(PROJECT),
            env=_environment(payload, registry),
            capture_output=True,
            text=True,
            timeout=float(payload.get("timeout_seconds", 7200)),
            shell=False,
        )
    finally:
        if lock is not None:
            _release_stage_lock(lock)
    ok = result.returncode == 0
    response = _envelope(
        method=method,
        status="succeeded" if ok else "failed",
        summary=_stage_summary(method, payload, resolved) if resolved is not None else {},
        artifacts=_stage_artifacts(method, payload, resolved) if resolved is not None else {},
        error_code=None if ok else "STAGE_FAILED",
        error=(
            None
            if ok
            else (result.stderr.strip() or result.stdout.strip() or f"stage exited with code {result.returncode}")[-2000:]
        ),
        stage=stage,
        exit_code=result.returncode,
        stdout=result.stdout[-20000:],
        stderr=result.stderr[-20000:],
        elapsed_seconds=round(time.monotonic() - started, 2),
    )
    return response


def _in_process_stage(
    stage: str,
    payload: Mapping[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Run a stage that is a plain Python call rather than a subprocess."""
    started = time.monotonic()
    try:
        result = METHODS[stage](payload, registry)
    except RegistryError as exc:
        return _failure("run_stage", "RUN_NOT_REGISTERED", str(exc), stage=stage,
                        elapsed_seconds=round(time.monotonic() - started, 2))
    except (KernelError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _failure(
            "run_stage",
            _error_code_for(exc),
            f"{type(exc).__name__}: {exc}",
            stage=stage,
            elapsed_seconds=round(time.monotonic() - started, 2),
        )
    response = dict(result)
    # Keep the method name stable for the one-entry tool while the inner
    # method keeps its own identity in ``summary``.
    response["method"] = "run_stage"
    response["stage"] = stage
    response["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return response




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
        return _failure(method, "RUN_NOT_REGISTERED", str(exc), stage=_stage_name(method, payload))
    except (KernelError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _failure(
            method,
            _error_code_for(exc),
            f"{type(exc).__name__}: {exc}",
            stage=_stage_name(method, payload),
        )


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
            resolved_for_job = None
            if args.method in STAGE_METHODS and payload.get("run_id"):
                resolved_for_job = _run_root_from_payload(payload, registry)
                error_code = _stage_prerequisite(args.method, payload, resolved_for_job)
                if error_code is not None:
                    raise KernelError(
                        f"{error_code}: "
                        + (
                            "this stage is not available in a migration workspace; "
                            "follow the fixed migration workflow"
                            if error_code == "STAGE_UNSUPPORTED"
                            else "required stage input is missing; run the preceding stage first"
                        )
                    )
            command = _command_for_job(args.method, payload, registry)
            context: dict[str, Any] = {}
            if resolved_for_job is not None:
                context = {
                    "run_id": resolved_for_job.get("run_id"),
                    "task_id": payload.get("task_id") or resolved_for_job.get("task_id"),
                    "run_root": str(resolved_for_job["run_root"]),
                    "task_root": (
                        str(resolved_for_job["task_root"])
                        if resolved_for_job.get("task_root") is not None
                        else None
                    ),
                }
            status = start_job(
                job_root=_job_root(),
                method=args.method,
                command=command,
                cwd=PROJECT,
                environment=_environment(payload, registry),
                context=context,
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
        command = _run_stage_command(payload, registry)
    elif method in {"source_scan", "extract", "curate", "prepare_reviews", "review", "finalize_review", "publish_library", "retrieval", "task", "report"}:
        command = _stage_command(method, payload, registry)
    elif method == "signal_prepare":
        command = _signal_prepare_command(payload, registry)
    elif method == "signal_embed":
        command = _signal_embed_command(payload, registry)
    elif method == "protocol_build":
        command = _protocol_build_command(payload, registry)
    elif method == "pipeline":
        command = _pipeline_command(payload, registry)
    elif method == "ops":
        command = _ops_command(payload, registry)
    else:
        raise KernelError(f"method does not support job mode: {method}")
    if method in STAGE_METHODS and payload.get("run_id"):
        # The job outlives this process; the wrapper holds the lock until the
        # stage exits so background stages still serialize with sync calls.
        resolved = _run_root_from_payload(payload, registry)
        lock_root = Path(resolved["task_root"] or resolved["run_root"])
        return [
            _python(),
            "-m",
            STAGE_LOCK_MODULE,
            "--lock-root",
            str(lock_root),
            "--",
            *command,
        ]
    return command


if __name__ == "__main__":
    raise SystemExit(main())
