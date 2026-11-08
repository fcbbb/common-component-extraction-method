from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import re
import shutil
import sys
from typing import Any, Iterable

from component_method.runtime_paths import release_root
from component_method.languages import normalize_language_config
from component_method.languages.registry import normalize_languages


PROJECT = release_root()
ROOT = Path(
    os.environ.get("COMPONENT_METHOD_RUN_ROOT", PROJECT / "repository" / "work")
).resolve()
EMBEDDING_INPUT_MANIFEST = (
    ROOT / "offline_embedding_50tasks_20261024" / "input_manifest.json"
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, Any]:
    files = []
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        file_sha256 = sha256_file(path)
        size = path.stat().st_size
        files.append({"path": relative, "bytes": size, "sha256": file_sha256})
        digest.update(relative.encode("utf-8") + b"\0" + file_sha256.encode("ascii") + b"\n")
    return {
        "root": str(root),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "tree_sha256": digest.hexdigest(),
        "files": files,
    }


def archive_failed_review_outputs(root: Path, task_id: str) -> dict[str, Any] | None:
    """Archive incomplete failed review directories before a resume attempt."""
    review_root = root / "runs" / task_id / "review_v1"
    summary_path = review_root / "summary.json"
    if not summary_path.is_file():
        return None
    summary = load_json(summary_path)
    if summary.get("status") != "failed":
        return None
    failed_ids = sorted(
        result["component_id"]
        for result in summary.get("results", [])
        if result.get("status") == "failed" and isinstance(result.get("component_id"), str)
    )
    pending = []
    for component_id in failed_ids:
        component_root = review_root / "components" / component_id
        if component_root.is_dir() and any(component_root.iterdir()):
            pending.append((component_id, component_root))
    if not pending:
        return None

    failed_root = review_root / "failed_attempts"
    attempt_numbers = []
    if failed_root.is_dir():
        for path in failed_root.iterdir():
            match = re.fullmatch(r"attempt_(\d+)", path.name)
            if path.is_dir() and match:
                attempt_numbers.append(int(match.group(1)))
    attempt_root = failed_root / f"attempt_{max(attempt_numbers, default=0) + 1:02d}"
    component_archive = attempt_root / "components"
    component_archive.mkdir(parents=True, exist_ok=False)

    archived = []
    for component_id, source in pending:
        destination = component_archive / component_id
        shutil.move(str(source), str(destination))
        archived.append(
            {
                "component_id": component_id,
                "source": str(source.relative_to(PROJECT)),
                "destination": str(destination.relative_to(PROJECT)),
                "tree": tree_manifest(destination),
            }
        )
    manifest = {
        "schema": "failed-review-resume-archive-v1",
        "task_id": task_id,
        "source_summary": str(summary_path.relative_to(PROJECT)),
        "source_summary_sha256": sha256_file(summary_path),
        "failed_component_ids": failed_ids,
        "archived": archived,
    }
    write_json(attempt_root / "archive_manifest.json", manifest)
    return manifest


def review_ready_for_component_failure_admission(summary: dict[str, Any]) -> bool:
    """Validate that only individual review components failed.

    The frozen reviewer reports the whole review as failed when any one component
    raises during schema validation.  The remaining successful results are still
    complete and can be published after the failed components are quarantined.
    """
    if summary.get("status") != "failed":
        return False
    component_ids = summary.get("component_ids")
    results = summary.get("results")
    published = summary.get("published_components")
    withheld = summary.get("withheld_components")
    if not all(isinstance(value, list) for value in (component_ids, results, published, withheld)):
        return False
    if not published or len(component_ids) != len(results):
        return False
    if any(not isinstance(component_id, str) for component_id in component_ids):
        return False
    if len(set(component_ids)) != len(component_ids):
        return False

    results_by_id = {}
    for result in results:
        if not isinstance(result, dict):
            return False
        component_id = result.get("component_id")
        if component_id not in component_ids or component_id in results_by_id:
            return False
        if result.get("status") not in {"ok", "failed"}:
            return False
        results_by_id[component_id] = result
    if set(results_by_id) != set(component_ids):
        return False

    published_set = set(published)
    withheld_set = set(withheld)
    if len(published_set) != len(published) or len(withheld_set) != len(withheld):
        return False
    if published_set & withheld_set:
        return False
    successful_set = {
        component_id
        for component_id, result in results_by_id.items()
        if result["status"] == "ok"
    }
    failed_set = set(component_ids) - successful_set
    if not failed_set or published_set | withheld_set != successful_set:
        return False
    if any(not results_by_id[component_id].get("publishable") for component_id in published_set):
        return False
    if any(results_by_id[component_id].get("publishable") for component_id in withheld_set):
        return False
    return (
        summary.get("successful_components") == len(successful_set)
        and summary.get("failed_components") == len(failed_set)
    )


def admit_review_component_failures(root: Path, task_id: str) -> dict[str, Any] | None:
    """Quarantine failed review components and admit the successful partition."""
    review_root = root / "runs" / task_id / "review_v1"
    summary_path = review_root / "summary.json"
    if not summary_path.is_file():
        return None
    summary = load_json(summary_path)
    if summary.get("completion_mode") == "component_failure_quarantine":
        return load_json(review_root / "component_failure_admission.json")
    if not review_ready_for_component_failure_admission(summary):
        return None

    original_summary_path = review_root / "summary.pre_component_failure_admission.json"
    original_manifest_path = review_root / "run_manifest.pre_component_failure_admission.json"
    manifest_path = review_root / "run_manifest.json"
    if not original_summary_path.exists():
        shutil.copy2(summary_path, original_summary_path)
    if manifest_path.is_file() and not original_manifest_path.exists():
        shutil.copy2(manifest_path, original_manifest_path)

    failed_results = [
        result for result in summary["results"] if result.get("status") == "failed"
    ]
    admission = {
        "schema": "review-component-failure-admission-v1",
        "task_id": task_id,
        "policy": "quarantine_failed_components_publish_successes",
        "original_summary": str(original_summary_path.relative_to(PROJECT)),
        "original_summary_sha256": sha256_file(original_summary_path),
        "published_component_ids": summary["published_components"],
        "withheld_component_ids": summary["withheld_components"],
        "quarantined_components": [
            {
                "component_id": result["component_id"],
                "error": result.get("error"),
            }
            for result in failed_results
        ],
    }
    admission_path = review_root / "component_failure_admission.json"
    write_json(admission_path, admission)

    admitted_summary = {
        **summary,
        "status": "completed",
        "upstream_status": summary["status"],
        "completion_mode": "component_failure_quarantine",
        "component_failure_admission": str(admission_path.relative_to(PROJECT)),
        "quarantined_components": [
            result["component_id"] for result in failed_results
        ],
    }
    write_json(summary_path, admitted_summary)
    if manifest_path.is_file():
        write_json(manifest_path, admitted_summary)
    return admission


def config() -> dict[str, Any]:
    return normalize_language_config(load_json(ROOT / "config.json"))


def tasks() -> list[dict[str, Any]]:
    path = ROOT / "tasks.json"
    if not path.is_file():
        raise RuntimeError(f"run prepare_batch.py first: {path}")
    config_path = ROOT / "config.json"
    defaults = normalize_languages(load_json(config_path) if config_path.is_file() else {})
    return [
        normalize_language_config(
            task if "languages" in task or "language" in task
            else {**task, "languages": defaults}
        )
        for task in load_json(path)["tasks"]
    ]


def repository_stats() -> dict[str, dict[str, Any]]:
    """Return frozen source-size metadata keyed by task instance ID."""
    if not EMBEDDING_INPUT_MANIFEST.is_file():
        return {}
    repositories = load_json(EMBEDDING_INPUT_MANIFEST).get("repositories", {})
    if not isinstance(repositories, dict):
        raise RuntimeError(
            f"invalid repositories in embedding manifest: {EMBEDDING_INPUT_MANIFEST}"
        )
    return repositories


def sort_tasks_by_repository_size(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort tasks by frozen code units, then bytes and eligible file count."""
    stats = repository_stats()

    def key(task: dict[str, Any]) -> tuple[int, int, int, str]:
        values = stats.get(task["instance_id"], {})
        return (
            int(values.get("units", sys.maxsize)),
            int(values.get("source_bytes", sys.maxsize)),
            int(values.get("eligible_files", sys.maxsize)),
            task["instance_id"],
        )

    return sorted(rows, key=key)


def select_tasks(
    task_ids: Iterable[str] | None = None,
    *,
    include_reserve: bool = False,
    require_direct: bool = False,
) -> list[dict[str, Any]]:
    requested = list(dict.fromkeys(task_ids or []))
    selected = set(requested)
    rows = []
    for task in tasks():
        if selected and task["instance_id"] not in selected:
            continue
        if task["cohort"] == "reserve" and not include_reserve and not selected:
            continue
        if require_direct and task.get("direct_status") != "completed":
            continue
        rows.append(task)
    by_id = {task["instance_id"]: task for task in rows}
    missing = selected - set(by_id)
    if missing:
        raise RuntimeError(f"unknown or excluded task IDs: {sorted(missing)}")
    if requested:
        return [by_id[instance_id] for instance_id in requested]
    return rows


def project_path(value: str) -> Path:
    return PROJECT / value


def task_root(instance_id: str) -> Path:
    return ROOT / "tasks" / instance_id


def completed_component_manifest(instance_id: str) -> Path | None:
    """Return the frozen completed component run, including continuations."""
    root = task_root(instance_id)
    candidates = [root / "task_attempts" / "task_01" / "run_manifest.json"]
    continuation_root = root / "continuations"
    if continuation_root.is_dir():
        candidates.extend(
            sorted(
                continuation_root.glob(
                    "*/task_attempts/task_01/run_manifest.json"
                )
            )
        )
    for path in candidates:
        if path.is_file() and load_json(path).get("status") == "completed":
            return path
    return None
