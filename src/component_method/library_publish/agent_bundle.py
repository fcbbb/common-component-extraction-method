"""Build and locate compact, read-only bundles for coding agents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..component_build.experiment import load_bundle_config, resolve_prompt
from ..component_build.workspace import COMPONENT_DIRECTORY, neutral_agent_text
from .component_cards import component_card, component_readme, index_line


BUNDLE_SCHEMA_VERSION = 7
BUNDLE_CONTAINER_PATH = COMPONENT_DIRECTORY


def _consumer_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Keep full execution records on the host, publish component facts only."""
    result = {key: item[key] for key in (
        "name", "summary", "capability", "type", "confidence", "members", "evidence",
        "entrypoints", "dependencies", "limitations", "relationships", "invariants",
        "variation_points", "guidance", "applicability", "integration_steps",
    ) if key in item}
    local = item.get("local_validation", {})
    validation = local.get("validation", {})
    capabilities = [
        {key: cap[key] for key in (
            "entrypoint", "path", "method", "availability",
            "validation_status", "contract", "example", "scope", "dependencies",
            "reason", "case_ids",
        ) if key in cap}
        for cap in validation.get("entrypoint_capabilities", []) if isinstance(cap, dict)
    ]
    review = validation.get("commonality_review", {})
    result["local_validation"] = {
        "status": local.get("status"),
        "validation": {
            "status": validation.get("status"),
            "entrypoint_capabilities": capabilities,
            "artifact_review": validation.get("artifact_review"),
            "commonality_review": {key: review[key] for key in (
                "status", "reason", "confirmed_members", "evidence", "limitations",
            ) if key in review},
            "case_results": {case_id: {"status": case.get("status")}
                             for case_id, case in validation.get("case_results", {}).items()},
        },
    }

    def neutral(value: Any) -> Any:
        if isinstance(value, str):
            return neutral_agent_text(value)
        if isinstance(value, list):
            return [neutral(child) for child in value]
        if isinstance(value, dict):
            return {key: neutral(child) for key, child in value.items()}
        return value

    return neutral(result)


def normalize_repository_id(value: Any) -> str:
    """Normalize a repository field to ``owner/repository``."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("repository id is empty")

    if raw.startswith("git@") and ":" in raw:
        raw = raw.split(":", 1)[1]
    elif raw.startswith(("http://", "https://")):
        raw = urlsplit(raw).path
    elif raw.startswith("www."):
        raw = raw.removeprefix("www.").split("/", 1)[-1]
    raw = raw.removesuffix(".git").strip("/")
    parts = [part for part in raw.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"expected owner/repository, got {value!r}")
    owner, repository = parts[-2:]
    if owner in {".", ".."} or repository in {".", ".."} or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", owner
    ) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository):
        raise ValueError(f"repository id contains unsupported characters: {value!r}")
    return f"{owner.lower()}/{repository.lower()}"


def normalize_commit(value: Any) -> str:
    commit = str(value or "").strip().lower()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise ValueError(f"expected a full git commit SHA, got {value!r}")
    return commit


def repository_store_key(repository_id: Any) -> str:
    return normalize_repository_id(repository_id).replace("/", "__")


def commit_store_key(commit: Any) -> str:
    return normalize_commit(commit)


def task_snapshot_key(
    instance: Any,
    *,
    image_name: str,
    white_box: bool = False,
    experiment_dir: Path | str | None = None,
) -> str:
    """Identify the task-visible workspace independently of component settings."""
    payload = {
        "schema": "masked-task-workspace-v3",
        "instance_id": instance.instance_id,
        "level": instance.level,
        "image_name": image_name,
        "patch": instance.patch or "",
        "fail_to_pass": instance.fail_to_pass or [],
        "repo_settings": instance.get_repo_settings(),
        "docker_runtime_config": instance.get_docker_runtime_config(),
        "white_box": white_box,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bundle_path(
    store_root: Path, repository_id: Any, commit: Any, *,
    task_key: str | None = None, construction_key: str | None = None,
) -> Path:
    base = (
        store_root.expanduser().resolve()
        / repository_store_key(repository_id)
        / commit_store_key(commit)
    )
    if task_key is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", task_key):
            raise ValueError(f"invalid task snapshot key: {task_key!r}")
        base = base / "masked-tasks" / task_key
    if construction_key is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", construction_key):
            raise ValueError(f"invalid bundle construction key: {construction_key!r}")
        return base / "bundle-v2-versions" / construction_key
    return base / "bundle-v2"


def _load_validated_components(audit_dir: Path) -> list[dict[str, Any]]:
    source = audit_dir / "unique_validated_components.jsonl"
    if not source.is_file():
        raise FileNotFoundError(f"community discovery output is missing {source}")

    components: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid component JSON at {source}:{line_number}: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"component at {source}:{line_number} is not a JSON object")
        if item.get("local_validation", {}).get("status") != "validated":
            continue
        if isinstance(item.get("component"), dict) and "artifact" in item["component"]:
            components.append(item)
            continue
        library = Path(str(item.get("library") or ""))
        if library.is_absolute() or ".." in library.parts:
            raise ValueError(f"unsafe component library path: {library}")
        library_path = (audit_dir / library).resolve()
        try:
            library_path.relative_to(audit_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"component library escapes discovery output: {library}") from exc
        if not library_path.is_file():
            raise FileNotFoundError(f"validated component library is missing: {library_path}")
        components.append(item)
    return components


def publish_agent_bundle(
    audit_dir: Path,
    store_root: Path,
    repository_id: Any,
    source_commit: Any,
    *,
    experiment_dir: Path | str | None = None,
    task_key: str | None = None,
    construction_key: str | None = None,
) -> Path:
    """Publish reviewed components using the current experiment's bundle settings."""
    repo = normalize_repository_id(repository_id)
    commit = normalize_commit(source_commit)
    audit_dir = audit_dir.expanduser().resolve()
    destination = bundle_path(
        store_root, repo, commit, task_key=task_key,
        construction_key=construction_key,
    )
    if destination.is_relative_to(audit_dir):
        raise ValueError("community component store must be outside the discovery audit directory")

    config = load_bundle_config(experiment_dir)
    items = _load_validated_components(audit_dir)
    structured = [item for item in items if isinstance(item.get("component"), dict) and "artifact" in item["component"]]
    if structured:
        if len(structured) != len(items):
            raise ValueError("publish historical records and artifact-v2 records as separate libraries")
        from .artifacts import publish_artifact_library

        return publish_artifact_library(
            [{"component": item["component"], "validation": item["local_validation"]["validation"]} for item in items],
            destination, repository=repo, source_commit=commit,
            manifest_metadata={"task_snapshot_key": task_key, **({"construction_key": construction_key} if construction_key else {})},
        )
    if config["sort_by"] == "original":
        pass
    elif config["sort_by"] == "members_count":
        items.sort(key=lambda item: (-len(item.get("members", [])), str(item.get("name") or "").casefold()))
    else:
        items.sort(key=lambda item: (str(item.get("name") or "").casefold(), str(item.get("primary_candidate_id") or "")))

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".bundle-staging-", dir=destination.parent))
    staging.chmod(0o755)
    backup: Path | None = None
    try:
        records = []
        libraries = []
        index_lines = ["# Component index", "", f"{len(items)} components. Each entry links to its usage README.", ""]
        for index, item in enumerate(items, 1):
            consumer_item = _consumer_metadata(item)
            bundle_id = f"component-{index:03d}"
            library = Path("components") / bundle_id / "component.py"
            library_path = staging / library
            library_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(audit_dir / item["library"], library_path)
            libraries.append(library.as_posix())
            card = component_card(consumer_item, library_path.read_text(encoding="utf-8"), bundle_id, library.as_posix())
            (staging / card["details_file"]).write_text(
                component_readme(card, guidance=consumer_item.get("guidance") if config["include_guidance"] else None),
                encoding="utf-8",
            )
            (staging / "audit").mkdir(exist_ok=True)
            (staging / card["audit_file"]).write_text(
                json.dumps({**consumer_item, "library": library.as_posix()}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            records.append({"bundle_id": bundle_id, "library": library.as_posix(),
                            "readme": card["details_file"], "audit_file": card["audit_file"]})
            index_lines.append(index_line(card, config["summary_max_chars"]))

        index_name = "INDEX.md"
        (staging / index_name).write_text("\n".join(index_lines) + "\n", encoding="utf-8")

        audit_status = "unknown"
        summary_path = audit_dir / "summary.json"
        if summary_path.is_file():
            try:
                audit_status = json.loads(summary_path.read_text(encoding="utf-8")).get(
                    "audit_status", "unknown"
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                audit_status = "unknown"
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "discovery_audit_status": audit_status,
            "method": "component_method",
            "repository": repo,
            "source_commit": commit,
            "task_snapshot_key": task_key,
            "construction_key": construction_key,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "component_count": len(records),
            "components_file": index_name,
            "libraries": libraries,
            "bundle_config": config,
            "consumer_metadata_schema": 2,
            "components": records,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        readme = (
            "# Component bundle\n\n"
            "Read [INDEX.md](INDEX.md) for the complete component list, then explore relevant components.\n\n"
            "Each `components/<id>/` directory contains `component.py` and `README.md` with source "
            "locations, entry signatures, contracts, examples, dependencies and validation scope.\n\n"
            "Review summaries are stored in `audit/<id>.json`; full execution records remain outside this bundle.\n"
        )
        (staging / "README.md").write_text(readme, encoding="utf-8")
        for staged_path in staging.rglob("*"):
            staged_path.chmod(0o755 if staged_path.is_dir() else 0o644)

        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise ValueError(f"refusing to replace non-directory bundle path: {destination}")
            backup_parent = Path(
                tempfile.mkdtemp(prefix=".bundle-backup-", dir=destination.parent)
            )
            backup_parent.rmdir()
            backup = backup_parent
            os.replace(destination, backup)
        try:
            os.replace(staging, destination)
        except Exception:
            if backup is not None and backup.exists():
                os.replace(backup, destination)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)

def validate_agent_bundle(
    path: Path,
    repository_id: Any,
    source_commit: Any,
    *,
    task_key: str | None = None,
) -> dict[str, Any]:
    """Validate a bundle against the task's repository revision and manifest."""
    path = path.expanduser().resolve()
    manifest_path = path / "manifest.json"
    readme_path = path / "README.md"
    if not path.is_dir() or not manifest_path.is_file() or not readme_path.is_file():
        raise FileNotFoundError(f"community component bundle is incomplete: {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_repo = normalize_repository_id(repository_id)
    expected_commit = normalize_commit(source_commit)
    if manifest.get("schema_version") not in {BUNDLE_SCHEMA_VERSION, 8}:
        raise ValueError(
            f"unsupported component bundle schema {manifest.get('schema_version')!r} at {path}"
        )
    if normalize_repository_id(manifest.get("repository")) != expected_repo:
        raise ValueError(f"component bundle repository does not match task repository: {path}")
    if normalize_commit(manifest.get("source_commit")) != expected_commit:
        raise ValueError(f"component bundle commit does not match task base commit: {path}")
    if task_key is not None and manifest.get("task_snapshot_key") != task_key:
        raise ValueError(f"component bundle task snapshot does not match task: {path}")

    components_file = str(manifest.get("components_file") or "INDEX.md")
    index_path = Path(components_file)
    if index_path.is_absolute() or ".." in index_path.parts:
        raise ValueError(f"unsafe component index path: {components_file}")
    resolved_index = (path / index_path).resolve()
    try:
        resolved_index.relative_to(path)
    except ValueError as exc:
        raise ValueError(f"component index escapes bundle: {components_file}") from exc
    if not resolved_index.is_file():
        raise FileNotFoundError(f"component bundle index is missing: {components_file}")
    if components_file != "INDEX.md":
        raise ValueError("component bundle must provide the complete INDEX.md")

    libraries = manifest.get("libraries")
    records = manifest.get("components")
    if not isinstance(libraries, list) or not isinstance(records, list):
        raise ValueError("component bundle must list its libraries and component metadata")
    if manifest.get("component_count") != len(records) or len(records) != len(libraries):
        raise ValueError(f"component bundle count does not match its manifest: {path}")
    if len(set(libraries)) != len(libraries):
        raise ValueError("component bundle contains duplicate library paths")
    for record, library in zip(records, libraries):
        if manifest.get("schema_version") == 8:
            from .artifacts import file_digest
            from component_method.languages.contracts import contained_path

            required = {record.get("library"), record.get("readme"), record.get("audit_file"),
                        *record.get("files", [])}
            hashes = record.get("file_sha256", {})
            if None in required or not required or set(hashes) != required:
                raise ValueError("artifact digest manifest does not cover every published file")
            for name, expected in hashes.items():
                if file_digest(contained_path(path, name)) != expected:
                    raise ValueError(f"artifact file digest changed: {name}")
        if record.get("library") != library:
            raise ValueError("component library does not match its manifest entry")
        for field in ("library", "readme", "audit_file"):
            relative = Path(str(record.get(field) or ""))
            resolved = (path / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not resolved.is_relative_to(path):
                raise ValueError(f"unsafe component metadata path: {relative}")
            if not resolved.is_file():
                raise FileNotFoundError(f"component bundle file is missing: {relative}")
        if Path(record["readme"]).parent != Path(library).parent:
            raise ValueError("component README must be beside its implementation")
    return manifest

def task_repository_and_commit(instance: Any) -> tuple[str, str]:
    """Extract the repository and immutable baseline commit from a task row."""
    metadata = getattr(instance, "metadata", {}) or {}
    repo_settings = instance.get_repo_settings() if hasattr(instance, "get_repo_settings") else {}
    repository = metadata.get("repo") or repo_settings.get("repository")
    commit = metadata.get("base_commit") or metadata.get("base_commit_id")
    if not repository:
        raise ValueError(f"task {getattr(instance, 'instance_id', '<unknown>')} has no repository id")
    if not commit:
        raise ValueError(f"task {getattr(instance, 'instance_id', '<unknown>')} has no base commit")
    return normalize_repository_id(repository), normalize_commit(commit)


def get_task_bundle(
    store_root: Path,
    instance: Any,
    *,
    image_name: str,
    white_box: bool = False,
    experiment_dir: Path | str | None = None,
    construction_key: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    repository, commit = task_repository_and_commit(instance)
    key = task_snapshot_key(
        instance, image_name=image_name, white_box=white_box,
        experiment_dir=experiment_dir,
    )
    path = bundle_path(
        store_root, repository, commit, task_key=key,
        construction_key=construction_key,
    )
    try:
        manifest = validate_agent_bundle(path, repository, commit, task_key=key)
        if construction_key is None or manifest.get("construction_key") == construction_key:
            return path, manifest
    except (FileNotFoundError, ValueError):
        pass
    raise FileNotFoundError(f"matching component bundle is missing: {path}")


def agent_bundle_prompt(experiment_dir: Path | str | None = None, *, bundle: Path | None = None) -> str:
    """Ask the coding agent to read the complete index and explore components itself."""
    if bundle is not None and json.loads((bundle / "manifest.json").read_text()).get("schema_version") == 8:
        return ("Read /testbed/component_bundle/INDEX.md and each relevant component README and audit record. "
                "Use the existing repository toolchain and the documented component source files. Check each "
                "entrypoint's validation_status and language before use. Direct reuse and reference-pattern "
                "adaptation are distinct delivery modes. Keep the supplied bundle read-only and do not download "
                "dependencies. Record used component IDs and entrypoints in /tmp/component_usage.json as "
                '{"component_usage": ["component identifier / entrypoint"]}.\n')
    template = resolve_prompt(experiment_dir, "usage/agent_bundle_prompt.txt")
    return (
        template.replace("{bundle_path}", BUNDLE_CONTAINER_PATH)
        .replace("{index_file}", "INDEX.md")
        .replace("{readme_file}", "README.md")
        .strip()
        + "\n"
    )
