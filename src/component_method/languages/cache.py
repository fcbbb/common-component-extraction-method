"""Per-repository cache for backend parsing and token-stream work.

Candidate generation asks the same backend for units and for clone/skeleton
streams several times.  Those calls are deterministic for a given
``file_id + source`` pair, so caching them avoids repeated libclang/tree-sitter
parses without changing the emitted facts.
"""

from __future__ import annotations

import hashlib
from typing import Any


class CachingSourceBackend:
    """Wrap a source backend and memoize deterministic parse products.

    The wrapper deliberately stays narrower than a general-purpose backend:
    it caches only ``extract_units`` and ``file_token_streams``.  All other
    attributes and methods are delegated unchanged.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._repository: Any = None
        self._units: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._streams: dict[tuple[str, str, str], tuple[tuple[Any, ...], str | None]] = {}

    @staticmethod
    def _source_key(file_id: str, source: str) -> tuple[str, str]:
        return file_id, hashlib.sha256(source.encode("utf-8")).hexdigest()

    def extract_units(self, file_id: str, source: str):
        key = self._source_key(file_id, source)
        cached = self._units.get(key)
        if cached is None:
            cached = tuple(self._backend.extract_units(file_id, source))
            self._units[key] = cached
        return list(cached)

    def file_token_streams(self, file_id: str, source: str, signal: str):
        key = (*self._source_key(file_id, source), signal)
        cached = self._streams.get(key)
        if cached is None:
            streams, error = self._backend.file_token_streams(file_id, source, signal)
            cached = (tuple(streams), error)
            self._streams[key] = cached
        return list(cached[0]), cached[1]

    def set_repository(self, root):
        if self._repository != root:
            self._units.clear()
            self._streams.clear()
            self._repository = root
        setter = getattr(self._backend, "set_repository", None)
        if setter is not None:
            return setter(root)
        return None

    def cache_stats(self) -> dict[str, int]:
        return {
            "unit_files": len(self._units),
            "stream_files_and_signals": len(self._streams),
        }

    def __getattr__(self, name):
        return getattr(self._backend, name)
