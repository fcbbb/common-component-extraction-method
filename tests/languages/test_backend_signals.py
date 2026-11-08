import json

import pytest

from component_method.languages.contracts import TokenStream
from component_method.languages.python.backend import PythonBackend
from component_method.signal_analysis import ast_signal, clone_signal, fusion
from tools.replay_python_baseline import FIXTURE


def test_backend_file_streams_keep_python_signal_order_and_rows():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    backend = PythonBackend()
    for entry in fixture["sources"]:
        for signal in ("clone", "skeleton"):
            streams, error = backend.file_token_streams(entry["file_id"], entry["source_code"], signal)
            for stream in streams:
                assert isinstance(stream, TokenStream)
                assert stream.language == "python"
                assert stream.backend_id == "python@1"
                assert stream.unit_key
                assert all(1 <= row <= len(entry["source_code"].splitlines()) for row in stream.rows)
            if signal == "skeleton" and entry["file_id"] == "broken.py":
                assert error.startswith("SyntaxError:")


def test_unit_tokens_preserve_original_coordinates():
    source = "FIRST = 1\n\nclass Parser:\n    @decorator\n    async def parse(self, value):\n        return value\n\nLAST = 2\n"
    backend = PythonBackend()
    units = backend.extract_units("parser.py", source)
    for unit in units:
        for stream in (backend.normalized_tokens(unit), backend.structural_tokens(unit)):
            assert stream.unit_key == unit.unit_key
            assert all(unit.span.start_line <= row <= unit.span.end_line for row in stream.rows)
    module = next(unit for unit in units if unit.kind == "module")
    assert set(backend.normalized_tokens(module).rows) == {1, 8}
    method = next(unit for unit in units if unit.kind == "method")
    assert set(backend.structural_tokens(method).rows) == {5, 6}
    cls = next(unit for unit in units if unit.kind == "class")
    assert backend.is_ancestor(cls, method)
    assert not backend.is_ancestor(method, cls)


class OpaqueBackend:
    def file_token_streams(self, file_id, source, signal):
        return [TokenStream(file_id, ("word",) * 20, (1,) * 20, file_id,
                            "opaque-id", "operator()", "fixture", "fixture@1")], None

    def describe_unit_id(self, unit_id):
        return {"kind": "namespace" if unit_id == "outer" else "function"}

    def is_ancestor(self, parent, child):
        return (parent["file_id"] == child["file_id"]
                and parent["unit_id"] == "outer" and child["unit_id"] == "inner")


@pytest.mark.parametrize("signal", [clone_signal, ast_signal])
def test_signal_algorithms_accept_backend_without_python_syntax(signal):
    result = signal.cluster_evidence([
        {"file_id": "one.ext", "source_code": "opaque input"},
        {"file_id": "two.ext", "source_code": "opaque input"},
    ], backend=OpaqueBackend())
    assert result["pairs"][0]["shared_tokens"] == 20
    assert result["unit_pairs"][0]["unit_a"] == "opaque-id"
    if signal is clone_signal:
        assert result["shared_units"][0]["name"] == "operator()"


def test_nested_normalization_delegates_to_backend():
    candidate = {"units": [
        {"file_id": file_id, "unit_id": unit_id}
        for file_id in ("one.ext", "two.ext") for unit_id in ("outer", "inner")
    ]}
    coarse = fusion._remove_nested_candidate_units([candidate], "coarse", backend=OpaqueBackend())
    leaf = fusion._remove_nested_candidate_units([candidate], "leaf", backend=OpaqueBackend())
    assert {unit["unit_id"] for unit in coarse[0]["units"]} == {"outer"}
    assert {unit["unit_id"] for unit in leaf[0]["units"]} == {"inner"}


def test_fusion_gets_unit_kind_from_backend():
    semantic = {"signal": "semantic", "pairs": [
        {"file_a": "one.ext", "unit_a": "inner", "file_b": "two.ext", "unit_b": "inner", "cosine": 0.99}
    ]}
    result = fusion.fuse_units([semantic], backend=OpaqueBackend())
    assert {unit["kind"] for unit in result["candidates"][0]["units"]} == {"function"}
