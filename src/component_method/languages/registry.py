"""Configuration normalization and deterministic source-file ownership."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .base import SourceBackend
from .contracts import relative_path, stable_digest


def normalize_languages(config: dict[str, Any]) -> list[dict[str, Any]]:
    if "languages" in config:
        values = config["languages"]
    else:
        values = [{"id": config.get("language", "python")}]
    if not isinstance(values, list) or not values:
        raise ValueError("languages must be a non-empty list")
    result = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"].strip():
            raise ValueError("each language must declare a non-empty id")
        row = deepcopy(value)
        for key in ("include", "exclude"):
            patterns = row.get(key, [])
            if not isinstance(patterns, list):
                raise ValueError(f"language {key} must be a list")
            for pattern in patterns:
                relative_path(pattern)
            if key in row:
                row[key] = sorted(set(patterns))
        result.append(row)
    ids = [row["id"] for row in result]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate language configuration")
    if "language" in config and ids != [config["language"]]:
        raise ValueError("language and languages configurations disagree")
    return sorted(result, key=lambda row: row["id"])


def normalize_language_config(config: dict[str, Any]) -> dict[str, Any]:
    return {**config, "languages": normalize_languages(config)}


def _matches(path: str, pattern: str) -> bool:
    # full_match implements root-relative globs with recursive ** (Python 3.13+).
    # On Python 3.12, a small segment matcher provides the same ownership rule.
    parts, patterns = PurePosixPath(path).parts, PurePosixPath(pattern).parts

    def match(pi: int, gi: int) -> bool:
        if gi == len(patterns):
            return pi == len(parts)
        if patterns[gi] == "**":
            return match(pi, gi + 1) or (pi < len(parts) and match(pi + 1, gi))
        return (pi < len(parts) and PurePosixPath(parts[pi]).match(patterns[gi])
                and match(pi + 1, gi + 1))

    return match(0, 0)


@dataclass(frozen=True)
class BackendSelection:
    entries: tuple[tuple[SourceBackend, dict[str, Any]], ...]

    def discover(self, root: Path, source_subdir: str, *,
                 preserve_backend_order: bool = False) -> list[tuple[Path, SourceBackend]]:
        root = root.resolve()
        owners: dict[str, tuple[Path, SourceBackend]] = {}
        for backend, options in self.entries:
            for path in backend.eligible_files(root, source_subdir):
                if not path.resolve().is_relative_to(root):
                    raise ValueError(f"source file escapes repository: {path}")
                file_id = path.relative_to(root).as_posix()
                if options.get("include") and not any(_matches(file_id, p) for p in options["include"]):
                    continue
                if any(_matches(file_id, p) for p in options.get("exclude", [])):
                    continue
                if file_id in owners:
                    raise ValueError(f"conflicting backend ownership: {file_id}")
                owners[file_id] = (path, backend)
        if preserve_backend_order:
            return list(owners.values())
        return [owners[key] for key in sorted(owners)]

    def single(self) -> SourceBackend:
        if len(self.entries) != 1:
            raise ValueError("this pipeline stage requires one language backend")
        return self.entries[0][0]

    def manifest(self) -> dict[str, Any]:
        return {
            "backends": [backend.identity().to_json() for backend, _ in self.entries],
            "path_rules_sha256": stable_digest([options for _, options in self.entries]),
        }


class LanguageRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, SourceBackend] = {}

    def register(self, backend: SourceBackend) -> None:
        if backend.language_id in self._backends:
            raise ValueError(f"backend already registered: {backend.language_id}")
        if backend.identity().backend_id != backend.backend_id:
            raise ValueError("backend identity disagrees with registration")
        self._backends[backend.language_id] = backend

    def resolve(self, config: dict[str, Any]) -> BackendSelection:
        entries = []
        for options in normalize_languages(config):
            try:
                backend = self._backends[options["id"]]
            except KeyError:
                raise ValueError(f"language backend is not installed: {options['id']}") from None
            if hasattr(backend, "configure"):
                backend = backend.configure(options)
            entries.append((backend, options))
        return BackendSelection(tuple(entries))


def default_registry() -> LanguageRegistry:
    from .python.backend import PythonBackend
    from .cpp.backend import CppBackend

    registry = LanguageRegistry()
    registry.register(PythonBackend())
    try:
        import clang.cindex
    except ImportError:
        pass
    else:
        registry.register(CppBackend())
    try:
        import tree_sitter
        import tree_sitter_java
    except ImportError:
        pass
    else:
        from .java.backend import JavaBackend

        registry.register(JavaBackend())
    return registry


def default_backend() -> SourceBackend:
    return default_registry().resolve({}).single()
