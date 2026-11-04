"""Run an independent tool-using agent over a frozen component library."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import shlex
import time
import traceback
from typing import Any

from .submission import validate_selection


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
CHECKER_PATH = Path(__file__).resolve().parent / "submission.py"
STANDARD_REPOSITORY_MASK_PATHS = ("/testbed", "/root/my_repo")
COMPLETION_MARKERS = {
    "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
    "MINI_SWE_AGENT_FINAL_OUTPUT",
}


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


def _has_completion_marker(command_output: dict[str, object]) -> bool:
    return any(
        line.strip() in COMPLETION_MARKERS
        for line in str(command_output.get("output", "")).splitlines()
    )


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


def run_retrieval_agent(
    request: RetrievalRequest,
    *,
    model_config: dict[str, Any],
    agent_class: type | None = None,
) -> dict[str, Any]:
    """Run retrieval with unlimited agent steps and validated file submission.

    ``agent_class`` may supply a transport-compatible DefaultAgent subclass for
    providers that emit non-Markdown shell envelopes. The retrieval behavior,
    mounts, prompts, validation and exit contract remain common.
    """
    from minisweagent.agents.default import DefaultAgent, FormatError, Submitted
    from minisweagent.environments.docker import DockerEnvironment
    from minisweagent.models import get_model
    from minisweagent.run.utils.save import save_traj

    base_agent = agent_class or DefaultAgent
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
            "step_limit": 0,
            "cost_limit": 0,
            "total_runtime_limit": None,
            "normal_exit": "validated coverage.json and selection.json plus completion marker",
            "task_repository_mounted": False,
            "repository_mask_paths": list(mask_paths),
        },
    )

    class CheckedRetrievalAgent(base_agent):
        def query(self) -> dict:
            response = super().query()
            _write_json(
                output / "state.json",
                {
                    "status": "running",
                    "model_calls": self.model.n_calls,
                    "reported_cost_usd": self.model.cost,
                },
            )
            save_traj(self, output / "checkpoint.traj.json", exit_status="Running", result="")
            print(
                f"retrieval model response {self.model.n_calls}; "
                f"reference cost {self.model.cost:.6f}",
                flush=True,
            )
            return response

        def has_finished(self, command_output: dict[str, object]) -> None:
            if not _has_completion_marker(command_output):
                return
            if command_output.get("returncode") != 0:
                raise FormatError("The final validation command failed. Repair selection.json and retry.")
            try:
                selection = validate_selection(
                    library,
                    selection_path,
                    expected_task_id=request.task_id,
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise FormatError(f"Submission validation failed: {exc}") from exc
            self.selection = selection
            raise Submitted(json.dumps(selection, ensure_ascii=False))

    mounts = [
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "128",
        "--memory",
        request.memory_limit,
        "--user",
        "10001:10001",
        "--mount",
        f"type=bind,source={library},target=/component-library,readonly",
        "--mount",
        f"type=bind,source={submission_dir},target=/component-output",
        "--mount",
        f"type=bind,source={CHECKER_PATH},target=/retrieval-tools/check_selection.py,readonly",
        "--mount",
        f"type=bind,source={catalog_path},target=/retrieval-tools/component_catalog.json,readonly",
    ]
    for path in mask_paths:
        mounts.extend([
            "--tmpfs",
            f"{path}:rw,nosuid,nodev,noexec,size=1m,mode=000",
        ])
    environment = None
    agent = None
    status = "EnvironmentError"
    result = ""
    extra = None
    started = time.monotonic()
    interrupted = False
    try:
        environment = DockerEnvironment(
            image=request.image,
            cwd="/component-library",
            env={
                "HOME": "/tmp",
                "TASK_ID": request.task_id,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PAGER": "cat",
            },
            timeout=request.command_timeout_seconds,
            container_timeout="infinity",
            run_args=mounts,
        )
        if mask_paths:
            checks = " && ".join(
                f"test ! -r {shlex.quote(path)}" for path in mask_paths
            )
            mask_check = environment.execute(checks)
            if mask_check.get("returncode") != 0:
                raise RuntimeError(
                    "task repository masking failed: " + str(mask_check.get("output", ""))
                )
        agent = CheckedRetrievalAgent(
            get_model(config=model_config),
            environment,
            system_template=(PROMPT_DIR / "retrieve_system.txt").read_text(encoding="utf-8"),
            instance_template="{{task}}",
            action_observation_template="Observation: {{output}}",
            timeout_template=(
                "The command timed out and was killed. Use a bounded non-interactive command and continue."
            ),
            format_error_template="Return exactly one complete Bash command in one Bash code block.",
            step_limit=0,
            cost_limit=0,
        )
        agent.selection = None
        _write_json(output / "state.json", {"status": "running", "model_calls": 0})
        status, result = agent.run(task)
    except KeyboardInterrupt:
        interrupted = True
        status = "StoppedByUser"
        result = "Retrieval stopped by user."
    except Exception as exc:
        status = type(exc).__name__
        result = str(exc)
        extra = {"traceback": traceback.format_exc()}
    finally:
        if agent is not None:
            save_traj(
                agent,
                output / "retrieval.traj.json",
                exit_status=status,
                result=result,
                extra_info=extra,
                instance_id=request.task_id,
            )
        if environment is not None:
            environment.cleanup()

    validated = getattr(agent, "selection", None) if agent is not None else None
    if validated is not None:
        _write_json(output / "result.json", validated)
    _write_json(
        output / "metadata.json",
        {
            "status": status,
            "elapsed_seconds": time.monotonic() - started,
            "model_calls": agent.model.n_calls if agent is not None else 0,
            "reported_cost_usd": agent.model.cost if agent is not None else 0,
            "selection_validated": validated is not None,
            "error": None if status == "Submitted" else result,
        },
    )
    _write_json(output / "state.json", {"status": status})
    if interrupted:
        raise KeyboardInterrupt(result)
    if status != "Submitted" or validated is None:
        detail = extra["traceback"] if extra else result
        raise RuntimeError(f"retrieval agent failed with {status}: {detail}")
    return validated
