from component_method.languages.cache import CachingSourceBackend
from component_method.languages.contracts import SourceUnit, Span, TokenStream


class CountingBackend:
    language_id = "fixture"
    backend_id = "fixture@1"

    def __init__(self):
        self.unit_calls = 0
        self.stream_calls = 0
        self.repository = None

    def set_repository(self, root):
        self.repository = root

    def extract_units(self, file_id, source):
        self.unit_calls += 1
        return [SourceUnit("fixture", "fixture@1", file_id, "function", "run", "run",
                           None, "void run()", Span(1, 1), source)]

    def file_token_streams(self, file_id, source, signal):
        self.stream_calls += 1
        return [TokenStream("key", ("id",), (1,), file_id, "run", "run",
                            "fixture", "fixture@1")], None

    def identity(self):
        return "identity"


def test_units_and_streams_are_cached_by_file_and_source():
    backend = CountingBackend()
    cache = CachingSourceBackend(backend)
    first = cache.extract_units("a.cpp", "void run() {}")
    second = cache.extract_units("a.cpp", "void run() {}")
    assert first == second
    assert backend.unit_calls == 1

    clone, error = cache.file_token_streams("a.cpp", "void run() {}", "clone")
    assert error is None
    assert clone == cache.file_token_streams("a.cpp", "void run() {}", "clone")[0]
    assert backend.stream_calls == 1

    cache.extract_units("a.cpp", "void run() { return; }")
    assert backend.unit_calls == 2
    assert cache.cache_stats()["unit_files"] == 2


def test_repository_change_clears_cache_and_delegates():
    backend = CountingBackend()
    cache = CachingSourceBackend(backend)
    cache.set_repository("/one")
    cache.extract_units("a.cpp", "void run() {}")
    cache.file_token_streams("a.cpp", "void run() {}", "skeleton")
    assert backend.unit_calls == backend.stream_calls == 1
    cache.set_repository("/one")
    assert backend.unit_calls == backend.stream_calls == 1
    cache.set_repository("/two")
    cache.extract_units("a.cpp", "void run() {}")
    assert backend.unit_calls == 2
    assert backend.repository == "/two"
    assert cache.identity() == "identity"
