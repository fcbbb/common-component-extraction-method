from dataclasses import replace

import pytest

from component_method.languages.contracts import (
    ArtifactFile, ComponentArtifact, SmokeCase, SourceUnit, Span, TokenStream, contained_path,
)
from component_method.languages.python.backend import PythonBackend
from component_method.languages.python.compat import (
    artifact_from_legacy, artifact_to_legacy, legacy_unit, smoke_from_legacy, smoke_to_legacy,
)
from component_method.source_scan.unit_extraction import extract_unit_sources


def test_source_identity_and_roundtrip():
    unit = PythonBackend().extract_units("src/parser.py", "def parse(value: str) -> str:\n    return value\n")[0]
    assert unit.schema == "source-unit-v2"
    assert unit.signature == "parse(value: str) -> str"
    assert SourceUnit.from_json(unit.to_json()) == unit
    assert replace(unit, source_code="changed").unit_key == unit.unit_key
    assert replace(unit, signature="parse(value: bytes)").unit_key != unit.unit_key
    assert replace(unit, language="other", backend_id="other@1").unit_key != unit.unit_key
    assert replace(unit, backend_id="python@2").unit_key != unit.unit_key
    corrupted = {**unit.to_json(), "unit_key": "wrong"}
    with pytest.raises(ValueError, match="identity"):
        SourceUnit.from_json(corrupted)


@pytest.mark.parametrize("source", [
    "", "# comment\n", "def unfinished(\n", "VALUE = 1\n",
    "@decorate\nasync def run(value):\n    return value\n",
    "class First:\n    @property\n    def value(self):\n        return 1\n\ndef last():\n    pass\n",
    "def f(x):\n    return x\ndef f(x):\n    return x + 1\n",
])
def test_python_legacy_order_and_spans(source):
    backend = PythonBackend()
    units = backend.extract_units("module.py", source)
    assert [legacy_unit(unit) for unit in units] == extract_unit_sources([
        {"file_id": "module.py", "source_code": source}
    ])
    assert len({unit.unit_key for unit in units}) == len(units)
    assert all(1 <= unit.span.start_line <= unit.span.end_line <= max(1, len(source.splitlines())) for unit in units)


@pytest.mark.parametrize("path", ["/tmp/file", "../file", "a/../file", "a//b", "./file", "C:/file", "a\\b", "", ".", "a/", "a\x00b"])
def test_artifact_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        ArtifactFile(path, "content")


def test_multifile_artifact_and_path_integrity(tmp_path):
    artifact = ComponentArtifact("cpp", "cpp@1", (
        ArtifactFile("include/parser.hpp", "declaration", "header"),
        ArtifactFile("src/parser.cpp", "definition"),
    ), ())
    assert ComponentArtifact.from_json(artifact.to_json()) == artifact
    with pytest.raises(ValueError, match="duplicate"):
        replace(artifact, files=(artifact.files[0], artifact.files[0]))
    with pytest.raises(ValueError, match="parent"):
        replace(artifact, files=(ArtifactFile("include", ""), artifact.files[0]))
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        contained_path(tmp_path, "link/file")
    assert contained_path(tmp_path, "new/file") == tmp_path / "new/file"


def test_lossless_python_converters():
    component = {
        "component_id": "one", "custom": {"value": [1, 2]},
        "library": {"path": "old/path.py", "content": "def parse():\n    pass\n", "extra": "preserved"},
        "entrypoints": [{"kind": "function", "name": "parse", "purpose": "Parse", "custom": True}],
    }
    artifact = artifact_from_legacy(component)
    assert artifact_to_legacy(ComponentArtifact.from_json(artifact.to_json())) == component
    case = {"case_id": "one", "entrypoint": "parse", "test_py": "def run(common):\n    common.parse()\n", "custom": [1]}
    converted_case = smoke_from_legacy(case)
    assert smoke_to_legacy(SmokeCase.from_json(converted_case.to_json())) == case
    assert component["library"]["path"] == "old/path.py"
    minimal = {"library": {"content": "value = 1"}}
    assert artifact_to_legacy(artifact_from_legacy(minimal)) == minimal


def test_contract_shape_errors():
    with pytest.raises(ValueError):
        Span(True, 2)
    with pytest.raises(ValueError):
        Span(4, 3)
    with pytest.raises(ValueError):
        TokenStream("unit", ("token",), ())
    assert PythonBackend().validate_source("broken.py", "def broken(")
    assert not PythonBackend().validate_source("ok.py", "value = 1")


def test_component_draft_normalizes_cpp_agent_aliases_and_paths():
    from component_method.component_build.contracts import normalize_component_draft

    component = {
        "component_id": "collection",
        "status": "ready",
        "name": "Collection",
        "summary": "Repeated collection harness",
        "type": "repeated_implementation",
        "confidence": 0.87,
        "members": [],
        "evidence": [],
        "artifact": {
            "schema": "component-artifact-v2",
            "language": "cpp",
            "backend_id": "cpp@1",
            "files": [
                {"path": "collection/include/cereal_test/collection.hpp", "role": "header", "content": "// header\n"},
                {"path": "collection/src/collection.cpp", "role": "source", "content": "// source\n"},
                {"path": "collection/smoke/collection.cpp", "role": "smoke", "content": "// smoke\n"},
            ],
            "entrypoints": [{"kind": "function", "qualified_name": "run"}],
        },
    }
    draft = normalize_component_draft(component, component_id="collection", origin_strategy="fixture")
    assert draft.status == "draft_ready"
    assert draft.confidence == "high"
    assert [item.path for item in draft.artifact.files] == [
        "include/cereal_test/collection.hpp",
        "src/collection.cpp",
        "smoke/collection.cpp",
    ]
