from dataclasses import replace
import json
import os

import pytest

from component_method.component_build.contracts import RepositoryContext
from component_method.component_build.validation.execution import execute_invocation
from component_method.languages.contracts import ArtifactFile, ComponentArtifact, Entrypoint, SmokeCase
from component_method.languages.registry import default_registry


def example(language, *, call=True):
    if language == "python":
        pytest.importorskip("ast")
        files = (ArtifactFile("helper.py", "def plus(a, b):\n    return a + b\n"),
                 ArtifactFile("common.py", "from helper import plus\ndef add(a, b):\n    return plus(a, b)\n"))
        entry = Entrypoint("function", "add", purpose="Add values")
        test = ArtifactFile("smoke.py", "def run(common):\n    " + ("assert common.add(2, 3) == 5\n" if call else "assert True\n"))
        metadata = {"module": "common"}
    elif language == "cpp":
        pytest.importorskip("clang.cindex")
        files = (ArtifactFile("include/adder.hpp", "#pragma once\nnamespace demo { int add(int a, int b); }\n", "header"),
                 ArtifactFile("src/adder.cpp", '#include "adder.hpp"\nnamespace demo { int add(int a, int b) { return a+b; } }\n'))
        entry = Entrypoint("function", "demo::add", purpose="Add values")
        test = ArtifactFile("smoke.cpp", '#include "adder.hpp"\nint main() { ' + ("return demo::add(2, 3) == 5 ? 0 : 1;" if call else "return 0;") + " }\n")
        metadata = {}
    else:
        pytest.importorskip("tree_sitter_java")
        files = (ArtifactFile("demo/Helper.java", "package demo; public class Helper { public static int plus(int a, int b) { return a+b; } }\n"),
                 ArtifactFile("demo/Adder.java", "package demo; public class Adder { public static int add(int a, int b) { return Helper.plus(a,b); } }\n"))
        entry = Entrypoint("method", "demo.Adder.add", purpose="Add values")
        test = ArtifactFile("Smoke.java", "public class Smoke { public static void main(String[] args) { " + ("if (demo.Adder.add(2,3) != 5) throw new AssertionError();" if call else "") + " } }\n")
        metadata = {"main_class": "Smoke"}
    artifact = ComponentArtifact(language, language + "@1", files, (entry,))
    case = SmokeCase("add-case", entry.entrypoint_id, (test,), metadata=metadata)
    return artifact, case


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
def test_backend_contract(language, tmp_path):
    artifact, case = example(language)
    backend = default_registry().resolve({"language": language}).single()
    assert not backend.validate_artifact(artifact)
    units = backend.artifact_units(artifact)
    assert units == backend.artifact_units(artifact)
    assert len({u.unit_key for u in units}) == len(units)
    for unit in units:
        for stream in (backend.normalized_tokens(unit), backend.structural_tokens(unit)):
            assert stream.unit_key == unit.unit_key
            assert all(unit.span.start_line <= r <= unit.span.end_line for r in stream.rows)
        assert backend.build_profile(unit).unit_key == unit.unit_key
    invocation = backend.prepare_smoke(artifact, case, tmp_path)
    compile((tmp_path / "driver/run.py").read_text(), "driver", "exec")
    assert invocation.workdir == "/work"
    published = backend.materialize_component(artifact, tmp_path / "published")
    assert set(published.files) == {f.path for f in artifact.files}
    assert backend.task_environment({}, tmp_path / "published").environment
    missing = replace(artifact.entrypoints[0], qualified_name="missing")
    assert backend.validate_entrypoints(replace(artifact, entrypoints=(missing,)))


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
@pytest.mark.parametrize("call", [True, False])
def test_actual_container_observations(language, call, tmp_path):
    image = os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE")
    if not image:
        pytest.skip("set COMPONENT_MULTILANGUAGE_IMAGE to run real offline toolchain tests")
    artifact, case = example(language, call=call)
    backend = default_registry().resolve({"language": language}).single()
    repository = tmp_path / "repository"
    repository.mkdir()
    context = RepositoryContext(repository, runtime_image=image)
    workspace = tmp_path / "run"
    invocation = backend.prepare_smoke(artifact, case, workspace)
    process, environment = execute_invocation(invocation, workspace, context)
    assert process.returncode == 0, process.to_json()
    observations = backend.parse_observations(invocation, process)
    assert observations[0].executed is call, observations
    assert environment["network_mode"] == "none"
    assert environment["repository_read_only"]
    assert environment["image_id"].startswith("sha256:")
    assert observations[0].evidence_level != "none"


def test_compilation_database_is_projected_to_runtime(tmp_path):
    artifact, case = example("cpp")
    source = artifact.files[1]
    artifact = replace(artifact, files=(artifact.files[0], replace(source, content=source.content.replace("a+b", "a+b+ADD_BIAS"))))
    database = [{"directory": str(tmp_path), "file": source.path,
                 "arguments": ["g++", "-DADD_BIAS=0", "-I", "include", "-c", source.path]}]
    (tmp_path / "compile_commands.json").write_text(json.dumps(database))
    backend = default_registry().resolve({"language": "cpp"}).single()
    backend.set_repository(tmp_path)
    assert not backend.validate_artifact(artifact)
    assert backend.runtime_flags(source.path) == ["-DADD_BIAS=0", "-I", "/repository/include"]
    invocation = backend.prepare_smoke(artifact, case, tmp_path / "run")
    assert "-DADD_BIAS=0" in (tmp_path / "run/driver/run.py").read_text()
    image = os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE")
    if image:
        process, _ = execute_invocation(invocation, tmp_path / "run", RepositoryContext(tmp_path, runtime_image=image))
        assert process.returncode == 0, process.to_json()
        assert backend.parse_observations(invocation, process)[0].executed


@pytest.mark.parametrize("language", ["python", "cpp", "java"])
def test_invalid_helper_is_rejected_even_with_valid_entrypoint(language):
    artifact, _ = example(language)
    suffix = {"python": "py", "cpp": "cpp", "java": "java"}[language]
    invalid = ArtifactFile("broken." + suffix, "def ( { invalid source\n")
    backend = default_registry().resolve({"language": language}).single()
    assert backend.validate_artifact(replace(artifact, files=(*artifact.files, invalid)))


def test_mixed_toolchain_preflight_in_real_container(tmp_path):
    image = os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE")
    if not image:
        pytest.skip("set COMPONENT_MULTILANGUAGE_IMAGE for toolchain preflight")
    from component_method.languages.preflight import inspect_configuration

    for language in ("python", "cpp", "java"):
        artifact, _ = example(language)
        for item in artifact.files:
            path = tmp_path / item.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.content)
    result = inspect_configuration({"repository_root": str(tmp_path), "runtime_image": image,
                                    "languages": [{"id": name} for name in ("python", "cpp", "java")]})
    assert result["source_files"] == {"python": 2, "cpp": 2, "java": 2}
    assert result["isolation"]["image_id"].startswith("sha256:")
    assert all(result["toolchains"][key]["returncode"] == 0 for key in ("cpp-0", "java-3", "python-5"))


@pytest.mark.parametrize("language", ["cpp", "java"])
def test_overloads_have_distinct_runtime_evidence(language, tmp_path):
    artifact, case = example(language)
    item = artifact.files[1]
    if language == "cpp":
        content = item.content + "namespace demo { double add(double a, double b) { return a+b; } }\n"
    else:
        content = item.content.rsplit("}", 1)[0] + "public static double add(double a, double b) { return a+b; } }\n"
    artifact = replace(artifact, files=(artifact.files[0], replace(item, content=content)))
    backend = default_registry().resolve({"language": language}).single()
    assert backend.validate_entrypoints(artifact)
    units = [u for u in backend.artifact_units(artifact) if u.file_id == item.path
             and u.qualified_name == artifact.entrypoints[0].qualified_name]
    assert len(units) == 2
    entries = tuple(replace(artifact.entrypoints[0], signature=u.signature,
                            metadata={"entrypoint_id": "double" if "double" in u.signature else "integer"}) for u in units)
    artifact = replace(artifact, entrypoints=entries)
    assert not backend.validate_artifact(artifact)
    invocation = backend.prepare_smoke(artifact, replace(case, entrypoint_id="integer"), tmp_path / "run")
    image = os.environ.get("COMPONENT_MULTILANGUAGE_IMAGE")
    if image:
        repository = tmp_path / "repository"
        repository.mkdir()
        process, _ = execute_invocation(invocation, tmp_path / "run", RepositoryContext(repository, runtime_image=image))
        assert process.returncode == 0, process.to_json()
        assert {o.entrypoint_id: o.executed for o in backend.parse_observations(invocation, process)} == {"integer": True, "double": False}
