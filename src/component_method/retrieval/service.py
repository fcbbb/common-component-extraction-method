"""Run an independent tool-using agent over a frozen component library."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import time
from typing import Any
import uuid

from component_method.agent_runtime import (
    AgentRunRequest,
    BackendSettings,
    create_agent_backend,
    selected_backend_name,
)

from .submission import validate_selection


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
CHECKER_PATH = Path(__file__).resolve().parent / "submission.py"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
STANDARD_REPOSITORY_MASK_PATHS = ("/testbed", "/root/my_repo")


@dataclass(frozen=True)
class RetrievalRequest:
    task_id: str
    problem_statement: str
    interface: str
    component_library: Path
    output_dir: Path
    image: str
    overwrite: bool = False
    command_timeout_seconds: int = 120
    total_timeout_seconds: int = 7200
    step_limit: int = 100
    memory_limit: str = "2g"
    repository_mask_paths: tuple[str, ...] = STANDARD_REPOSITORY_MASK_PATHS


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _text(value: Any, *, limit: int = 500) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1].rstrip() + "…"


def build_component_catalog(library: Path) -> dict[str, Any]:
    """Build a compact, complete first-pass catalog from a published library."""
    library = library.resolve()
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for component in manifest.get("components", []):
        audit_relative = component.get("audit_file")
        audit = {}
        if isinstance(audit_relative, str):
            audit = json.loads((library / audit_relative).read_text(encoding="utf-8"))
        contract = audit.get("protocol_contract")
        if not isinstance(contract, dict):
            contract = {}
        consumers = []
        for consumer in contract.get("consumers", []):
            if isinstance(consumer, dict):
                consumers.append({
                    "location": _text(
                        ":".join(filter(None, [consumer.get("file_id"), consumer.get("unit_id")]))
                    ),
                    "role": _text(consumer.get("role"), limit=240),
                })
            elif isinstance(consumer, str):
                consumers.append({"location": "", "role": _text(consumer, limit=240)})
        entrypoints = [
            _text(entry.get("name"), limit=120)
            for entry in audit.get("entrypoints", [])
            if isinstance(entry, dict) and entry.get("name")
        ]
        records.append({
            "bundle_id": component.get("bundle_id"),
            "component_id": audit.get("component_id"),
            "name": _text(audit.get("name") or component.get("bundle_id"), limit=180),
            "capability": _text(audit.get("capability") or audit.get("summary")),
            "capability_family": _text(contract.get("capability_family"), limit=120),
            "semantic_domain": _text(contract.get("semantic_domain")),
            "extension_trigger": _text(contract.get("extension_trigger")),
            "consumers": consumers,
            "reuse_interface": contract.get("reuse_interface"),
            "boundary": _text(contract.get("boundary")),
            "entrypoints": entrypoints,
            "protocol_status": audit.get("protocol_status"),
            "readme": component.get("readme"),
            "audit_file": audit_relative,
        })
    return {
        "schema_version": 1,
        "component_count": len(records),
        "components": records,
    }


def _validated_mask_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    normalized = []
    for value in paths:
        path = Path(value)
        if not value.startswith("/") or value == "/" or any(character in value for character in ",:"):
            raise ValueError(f"repository mask path must be a safe absolute path: {value!r}")
        clean = path.as_posix()
        if clean not in normalized:
            normalized.append(clean)
    return tuple(normalized)


def _repository_mask_paths(
    manifest: dict[str, Any], configured_paths: tuple[str, ...]
) -> tuple[str, ...]:
    repository = manifest.get("repository")
    if not isinstance(repository, str) or not repository.strip():
        raise ValueError("component library manifest must declare repository")
    repository_name = repository.strip().rstrip("/").rsplit("/", 1)[-1]
    if repository_name.endswith(".git"):
        repository_name = repository_name[:-4]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repository_name):
        raise ValueError(f"invalid component library repository: {repository!r}")
    return _validated_mask_paths(
        tuple(dict.fromkeys((*configured_paths, f"/{repository_name}")))
    )


def render_retrieval_task(request: RetrievalRequest) -> str:
    """Render task metadata without inlining the component catalog."""
    template = (PROMPT_DIR / "retrieve_instance.txt").read_text(encoding="utf-8")
    return (
        template.replace("{{task_id}}", request.task_id)
        .replace("{{problem_statement}}", request.problem_statement)
        .replace("{{interface}}", request.interface)
    )


def _retrieval_system_prompt(task_id: str) -> str:
    return (PROMPT_DIR / "retrieve_system.txt").read_text(encoding="utf-8").replace(
        '"$TASK_ID"', shlex.quote(task_id)
    )


def _retrieval_checker_command(task_id: str) -> tuple[str, ...]:
    return (
        "python",
        "/retrieval-tools/check_selection.py",
        "--library",
        "/component-library",
        "--coverage",
        "/component-output/coverage.json",
        "--selection",
        "/component-output/selection.json",
        "--task-id",
        task_id,
        "--submit",
    )


def _model_route(model_config: dict[str, Any]) -> tuple[str, str, str]:
    model = model_config.get("model_name")
    model_kwargs = model_config.get("model_kwargs")
    base_url = model_kwargs.get("api_base") if isinstance(model_kwargs, dict) else None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not isinstance(model, str) or not model:
        raise ValueError("retrieval model_config requires model_name")
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("retrieval model_config requires model_kwargs.api_base")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    return model, base_url, api_key


def _run_dsh_retrieval(
    request: RetrievalRequest,
    *,
    model_config: dict[str, Any],
    library: Path,
    output: Path,
    submission_dir: Path,
    selection_path: Path,
    task: str,
    catalog_path: Path,
    mask_paths: tuple[str, ...],
    backend_name: str,
) -> dict[str, Any]:
    import docker

    if request.total_timeout_seconds < 1:
        raise ValueError("retrieval total_timeout_seconds must be positive")
    if request.step_limit < 1:
        raise ValueError("retrieval step_limit must be positive")
    model, base_url, api_key = _model_route(model_config)
    safe_task = re.sub(r"[^A-Za-z0-9_-]+", "-", request.task_id)[:48]
    container_name = f"component-retrieval-{safe_task}-{uuid.uuid4().hex[:10]}"
    client = docker.from_env()
    container = None
    backend_result = None
    validated = None
    started = time.monotonic()
    status = "EnvironmentError"
    error = None
    try:
        tmpfs = {"/tmp": "rw,nosuid,nodev,size=512m,mode=1777"}
        tmpfs.update({
            path: "rw,nosuid,nodev,noexec,size=1m,mode=000"
            for path in mask_paths
        })
        container = client.containers.create(
            image=request.image,
            entrypoint=[],
            name=container_name,
            command=["sleep", "infinity"],
            working_dir="/component-library",
            user="10001:10001",
            volumes={
                str(library): {"bind": "/component-library", "mode": "ro"},
                str(submission_dir): {"bind": "/component-output", "mode": "rw"},
                str(CHECKER_PATH): {
                    "bind": "/retrieval-tools/check_selection.py",
                    "mode": "ro",
                },
                str(catalog_path): {
                    "bind": "/retrieval-tools/component_catalog.json",
                    "mode": "ro",
                },
            },
            network_mode="none",
            read_only=True,
            tmpfs=tmpfs,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            pids_limit=128,
            mem_limit=request.memory_limit,
            labels={"featurebench.component_retrieval.agent": safe_task},
        )
        container.start()
        if mask_paths:
            checks = " && ".join(
                f"test ! -r {shlex.quote(path)}" for path in mask_paths
            )
            mask_check = container.exec_run(
                ["/bin/bash", "-lc", checks],
                user="10001:10001",
                environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            if mask_check.exit_code != 0:
                detail = mask_check.output
                if isinstance(detail, bytes):
                    detail = detail.decode("utf-8", errors="replace")
                raise RuntimeError(f"task repository masking failed: {detail}")

        backend = create_agent_backend(
            BackendSettings(
                api_key=api_key,
                base_url=base_url,
                repository_root=REPOSITORY_ROOT,
            ),
            name=backend_name,
        )
        _write_json(output / "state.json", {"status": "running", "model_calls": 0})
        backend_result = backend.run(
            AgentRunRequest(
                run_id=safe_task,
                role="retrieval",
                model=model,
                system_prompt=_retrieval_system_prompt(request.task_id),
                task_prompt=task,
                output_dir=output,
                container_name=container_name,
                container_cwd="/component-library",
                command_timeout_seconds=request.command_timeout_seconds,
                total_timeout_seconds=request.total_timeout_seconds,
                step_limit=request.step_limit,
                submission_mode="files",
                submission_role="retrieval",
                submission_checker_command=_retrieval_checker_command(request.task_id),
            )
        )
        status = backend_result.status
        error = backend_result.error
        if status == "Submitted":
            validated = validate_selection(
                library,
                selection_path,
                expected_task_id=request.task_id,
                coverage_path=submission_dir / "coverage.json",
            )
            _write_json(output / "result.json", validated)
        else:
            raise RuntimeError(
                "retrieval agent did not submit a validated selection "
                f"(status={status}, error={error})"
            )
    except Exception as exc:
        if status in {"EnvironmentError", "Submitted"}:
            status = type(exc).__name__
        if error is None:
            error = str(exc)
        raise
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        _write_json(
            output / "metadata.json",
            {
                "status": status,
                "elapsed_seconds": time.monotonic() - started,
                "model_calls": backend_result.model_calls if backend_result else 0,
                "input_tokens": backend_result.input_tokens if backend_result else None,
                "output_tokens": backend_result.output_tokens if backend_result else None,
                "reported_cost_usd": (
                    backend_result.reported_cost_usd if backend_result else None
                ),
                "selection_validated": validated is not None,
                "agent_backend": backend_name,
                "session_id": backend_result.session_id if backend_result else None,
                "error": error,
            },
        )
        _write_json(output / "state.json", {"status": status})
    return validated


def run_retrieval_agent(
    request: RetrievalRequest,
    *,
    model_config: dict[str, Any],
) -> dict[str, Any]:
    """Run retrieval with validated file submission and bounded DSH execution."""
    backend_name = selected_backend_name()
    library = request.component_library.expanduser().resolve()
    output = request.output_dir.expanduser().resolve()
    if not library.is_dir():
        raise FileNotFoundError(f"component library does not exist: {library}")
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest.get("components"), list) or not manifest["components"]:
        raise ValueError("component library is empty")
    if output.exists():
        if not request.overwrite:
            raise FileExistsError(f"retrieval output already exists: {output}")
        shutil.rmtree(output)

    submission_dir = output / "submission"
    selection_path = submission_dir / "selection.json"
    submission_dir.mkdir(parents=True)
    submission_dir.chmod(0o777)
    task = render_retrieval_task(request)
    (output / "agent_task.txt").write_text(task, encoding="utf-8")
    catalog = build_component_catalog(library)
    catalog_path = output / "component_catalog.json"
    _write_json(catalog_path, catalog)
    mask_paths = _repository_mask_paths(manifest, request.repository_mask_paths)
    _write_json(
        output / "run_manifest.json",
        {
            "task_id": request.task_id,
            "model": model_config.get("model_name"),
            "component_library": str(library),
            "component_library_sha256": hashlib.sha256(
                json.dumps(_file_hashes(library), sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "component_count": len(manifest["components"]),
            "component_catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
            "agent_backend": backend_name,
            "step_limit": request.step_limit,
            "cost_limit": 0,
            "total_runtime_limit": request.total_timeout_seconds,
            "normal_exit": "validated coverage.json and selection.json plus completion marker",
            "task_repository_mounted": False,
            "repository_mask_paths": list(mask_paths),
        },
    )

    return _run_dsh_retrieval(
        request,
        model_config=model_config,
        library=library,
        output=output,
        submission_dir=submission_dir,
        selection_path=selection_path,
        task=task,
        catalog_path=catalog_path,
        mask_paths=mask_paths,
        backend_name=backend_name,
    )
