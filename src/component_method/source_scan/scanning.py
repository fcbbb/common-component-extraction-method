"""Discover production sources through configured language backends."""

from pathlib import Path
from typing import Any, Iterator

from component_method.languages.base import SourceBackend
from component_method.languages.registry import BackendSelection, LanguageRegistry, default_registry, normalize_languages


def source_files(root: Path, source_subdir: str, selection: BackendSelection
                 ) -> Iterator[tuple[dict[str, str], SourceBackend]]:
    root = root.resolve()
    for backend, _ in selection.entries:
        if hasattr(backend, "set_repository"):
            backend.set_repository(root)
    for path, backend in selection.discover(root, source_subdir, preserve_backend_order=True):
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if source.strip():
            yield {"file_id": path.relative_to(root).as_posix(), "source_code": source}, backend


def task_backends(task: dict[str, Any], registry: LanguageRegistry | None = None, *,
                   defaults: dict[str, Any] | None = None) -> BackendSelection:
    if "language" not in task and "languages" not in task:
        task = {**task, "languages": normalize_languages(defaults or {})}
    return (registry or default_registry()).resolve(task)
