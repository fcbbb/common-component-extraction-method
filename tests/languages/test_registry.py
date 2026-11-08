from copy import deepcopy
from pathlib import Path

import pytest

from component_method.languages import LanguageRegistry, default_registry, normalize_language_config
from component_method.languages.contracts import BackendIdentity
from component_method.languages.python.backend import PythonBackend
from component_method.languages.registry import normalize_languages


@pytest.mark.parametrize("config", [{}, {"language": "python"}, {"languages": [{"id": "python"}]}])
def test_default_and_legacy_config(config):
    assert normalize_language_config(config)["languages"] == [{"id": "python"}]
    selected = default_registry().resolve(config)
    assert selected.entries[0][0].backend_id == "python@1"
    identity = selected.manifest()["backends"][0]
    assert identity["parser"] == "stdlib-ast"
    assert len(identity["implementation_sha256"]) == 64


@pytest.mark.parametrize("config", [
    {"languages": []}, {"languages": None}, {"languages": ["python"]},
    {"languages": [{"id": ""}]}, {"languages": [{"id": "python"}, {"id": "python"}]},
    {"language": "python", "languages": [{"id": "cpp"}]},
    {"languages": [{"id": "python", "include": "*.py"}]},
    {"languages": [{"id": "python", "include": ["../*.py"]}]},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        normalize_languages(config)


def test_missing_and_duplicate_registration():
    registry = default_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(PythonBackend())
    with pytest.raises(ValueError, match="not installed"):
        registry.resolve({"language": "missing-backend"})


def test_discovery_filters_and_conflicts(tmp_path):
    for name in ("src/root.py", "src/nested/child.py", "tests/test_a.py", "src/test_a.py", "src/a_test.py", "src/file.cpp"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1", encoding="utf-8")
    config = {"languages": [{"id": "python", "include": ["src/**/*.py"], "exclude": ["src/nested/**"]}]}
    before = deepcopy(config)
    selection = default_registry().resolve(config)
    found = selection.discover(tmp_path, ".")
    assert [p.relative_to(tmp_path).as_posix() for p, _ in found] == ["src/root.py"]
    assert config == before

    class OtherBackend(PythonBackend):
        language_id = "other"
        backend_id = "other@1"

        def identity(self):
            return BackendIdentity("other", "1", "fixture", "1", "0" * 64)

    registry = default_registry()
    registry.register(OtherBackend())
    with pytest.raises(ValueError, match="conflicting backend ownership"):
        registry.resolve({"languages": [{"id": "other"}, {"id": "python"}]}).discover(tmp_path, ".")


def test_registration_order_does_not_change_results(tmp_path):
    class FixtureBackend:
        def __init__(self, language_id):
            self.language_id = language_id
            self.backend_id = f"{language_id}@1"

        def identity(self):
            return BackendIdentity(self.language_id, "1", "fixture", "1", "0" * 64)

        def eligible_files(self, root, source_subdir):
            return [root / self.language_id]

    configurations = {"languages": [{"id": "z"}, {"id": "a"}]}
    registries = [LanguageRegistry(), LanguageRegistry()]
    for registry, names in zip(registries, [("a", "z"), ("z", "a")]):
        for name in names:
            registry.register(FixtureBackend(name))
    selections = [registry.resolve(configurations) for registry in registries]
    assert selections[0].manifest() == selections[1].manifest()
    assert [path.name for path, _ in selections[0].discover(tmp_path, ".")] == ["a", "z"]
    assert [backend.backend_id for _, backend in selections[1].discover(tmp_path, ".")] == ["a@1", "z@1"]


def test_discovery_rejects_external_symlink(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "outside.py"
    target.write_text("value = 1", encoding="utf-8")
    (root / "linked.py").symlink_to(target)
    with pytest.raises(ValueError, match="escapes"):
        default_registry().resolve({}).discover(root, ".")


def test_backend_digest_tracks_legacy_implementation(monkeypatch):
    backend = PythonBackend()
    before = backend.identity().implementation_sha256
    read_bytes = Path.read_bytes

    def changed_bytes(path):
        content = read_bytes(path)
        return content + b"\n# changed implementation\n" if path.name == "units.py" else content

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    assert backend.identity().implementation_sha256 != before


def test_path_rule_manifest_tracks_configuration():
    registry = default_registry()
    first = registry.resolve({"languages": [{"id": "python", "include": ["src/**/*.py"]}]})
    second = registry.resolve({"languages": [{"id": "python", "include": ["lib/**/*.py"]}]})
    assert first.manifest()["path_rules_sha256"] != second.manifest()["path_rules_sha256"]
