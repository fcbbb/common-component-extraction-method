"""Execute smoke drivers and verify coverage against actual original callable invocations."""

import pytest

from component_method.component_build.validation.runtime import validate_callable_artifact
from component_method.component_build.validation.service import _runtime_exercises_path


@pytest.mark.parametrize('layout', ['', 'src/'])
def test_repository_grounding_supports_package_layouts_and_rejects_missing_modules(tmp_path, layout):
    from component_method.component_build.context.component_context import _validate_common_reference

    original = 'from .helpers import normalize_input\ndef normalize(value):\n    return normalize_input(value)\n'
    helper = 'def normalize_input(value):\n    return value.strip().lower()\n'
    member = layout + 'source_package/operation.py'
    sources = {member: original, layout + 'source_package/helpers.py': helper}
    extracted = original.replace('from .helpers', 'from source_package.helpers')
    result = _validate_common_reference(
        {'library': {'content': extracted}}, {'cluster_id': 'normalize', 'members': [member]},
        sources, tmp_path / 'grounding', allow_repository_imports=True,
    )
    assert result['status'] == 'ok', result
    assert result['repository_imports'] == [layout + 'source_package/helpers.py']
    missing = _validate_common_reference(
        {'library': {'content': extracted.replace('source_package.helpers', 'source_package.missing')}},
        {'cluster_id': 'normalize', 'members': [member]}, sources,
        tmp_path / 'missing', allow_repository_imports=True,
    )
    assert missing['status'] == 'ungrounded', missing
    assert 'source_package.missing' in missing['invented_imports']


def test_component_imports_visible_repository_helpers_without_copying_them(tmp_path):
    repo = tmp_path / "repo"
    package = repo / "source_package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    helper = "def normalize_input(value):\n    return value.strip().lower()\n"
    original = "from .helpers import normalize_input\ndef normalize(value):\n    return normalize_input(value)\n"
    (package / "helpers.py").write_text(helper)
    (package / "operation.py").write_text(original)
    extracted = original.replace("from .helpers", "from source_package.helpers")
    result = validate_callable_artifact(
        component_id="normalize", library_content=extracted,
        smoke_content="def run(common):\n    assert common.normalize(' A ') == 'a'\n    return True\n",
        entrypoints=[{"name": "normalize", "kind": "function"}], repo_root=repo,
        output_dir=tmp_path / "runtime", grounding_members=["source_package/operation.py"],
        all_sources={"source_package/operation.py": original, "source_package/helpers.py": helper},
    )
    assert result["status"] == "ok", result
    assert result["grounding"]["repository_imports"] == ["source_package/helpers.py"]
    assert (package / "operation.py").read_text() == original


def test_same_mount_cannot_recreate_an_original_package_relative_import(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "helpers.py").write_text("def clean(value): return value.strip()\n")
    result = validate_callable_artifact(
        component_id="normalize", library_content="from .helpers import clean\ndef normalize(value): return clean(value)\n",
        smoke_content="def run(common):\n    assert common.normalize(' A ') == 'A'\n    return True\n",
        entrypoints=[{"name": "normalize", "kind": "function"}], repo_root=repo,
        output_dir=tmp_path / "runtime",
    )
    assert result["status"] != "ok", result
    assert result["import"]["ok"] is False
    assert "attempted relative import with no known parent package" in result["call"]["stderr"]


def test_structured_coverage_tracks_callable_without_argument_constraints(tmp_path):
    from component_method.component_build.validation.service import _capability_path

    result = execute(tmp_path, "def scale(value, mode='identity'):\n    return value\n",
                     "def run(common):\n    assert common.scale(3, mode='identity') == 3\n    return True\n")
    names = {"scale": {"kind": "function"}}
    path = _capability_path({"entrypoint": "scale", "method": ""}, names)
    assert path == "scale"
    assert _runtime_exercises_path(result, "scale", path)


def execute(tmp_path, library, smoke, name="scale", kind="function", entrypoints=None):
    return validate_callable_artifact(
        component_id=name, library_content=library, smoke_content=smoke,
        entrypoints=entrypoints or [{"name": name, "kind": kind}], repo_root=tmp_path,
        output_dir=tmp_path / "runtime",
    )


@pytest.mark.parametrize("body", [
    "if False:\n        common.scale(mode='log')",
    "scale = common.scale\n    scale = lambda **kwargs: 3\n    assert scale(mode='log') == 3",
    "def never_called():\n        common.scale(mode='log')",
    "hidden = lambda: common.scale(mode='log')",
    "return True\n    common.scale(mode='log')",
])
def test_unexecuted_or_replaced_entrypoints_are_not_validated(tmp_path, body):
    result = execute(tmp_path, "def scale(mode):\n    raise AssertionError('real callable invoked')\n",
                     f"def run(common):\n    {body}\n    return True\n")
    assert result["status"] == "smoke_does_not_call_entrypoints", result
    assert result["call"]["ok"] is False
    assert not _runtime_exercises_path(result, "scale", "scale(mode='log')")


@pytest.mark.parametrize("body", [
    "if False:\n        common.scale(mode='log')\n    common.scale(mode='identity')",
    "scale = common.scale\n    scale = lambda **kwargs: 3\n    scale(mode='log')\n    common.scale(mode='identity')",
    "common.scale(mode='identity')\n    mode = 'log'",
    "mode = 'log'\n    mode = 'identity'\n    common.scale(mode=mode)",
])
def test_other_actual_call_does_not_credit_an_unexecuted_input_mode(tmp_path, body):
    result = execute(tmp_path, "def scale(mode):\n    return mode\n",
                     f"def run(common):\n    {body}\n    return True\n")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "scale", "scale(mode='identity')")
    assert not _runtime_exercises_path(result, "scale", "scale(mode='log')")


def test_variable_alias_helper_and_default_arguments_record_actual_values(tmp_path):
    result = execute(tmp_path, "def scale(value=3, *, mode='identity'):\n    return value\n", """
def helper(function, value, mode):
    return function(value, mode=mode)
def run(common):
    mode = 'identity'
    alias = common.scale
    assert helper(alias, 3, mode) == 3
    assert common.scale() == 3
    assert common.scale is alias
    return True
""")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "scale", "scale(3, mode='identity')")
    assert not _runtime_exercises_path(result, "scale", "scale(3, mode='log')")


@pytest.mark.parametrize("awaited", [False, True])
def test_async_entrypoint_requires_execution_of_coroutine(tmp_path, awaited):
    call = "assert await common.scale('identity') == 'identity'" if awaited else "common.scale('identity')"
    result = execute(tmp_path, "async def scale(mode):\n    return mode\n",
                     f"async def run(common):\n    {call}\n    return True\n")
    assert result["status"] == ("ok" if awaited else "smoke_does_not_call_entrypoints"), result
    assert _runtime_exercises_path(result, "scale", "scale(mode='identity')") is awaited


def test_class_constructor_and_method_coverage_remain_separate(tmp_path):
    result = execute(tmp_path, "class Transform:\n    def identity(self, value):\n        return value\n    def log(self, value):\n        raise AssertionError('unexecuted')\n", """
def run(common):
    class Concrete(common.Transform):
        pass
    obj = Concrete()
    assert isinstance(obj, common.Transform)
    assert obj.identity(3) == 3
    if False:
        obj.log(3)
    log = obj.log
    log = lambda value: value
    assert log(3) == 3
    return True
""", name="Transform", kind="class")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "Transform", "Transform")
    assert _runtime_exercises_path(result, "Transform", "Transform.identity(3)")
    assert not _runtime_exercises_path(result, "Transform", "Transform.log(3)")


def test_module_initialization_does_not_credit_run_coverage(tmp_path):
    result = execute(tmp_path, "class Transform: pass\n", """
import common
obj = common.Transform()
def run(common):
    return True
""", name="Transform", kind="class")
    assert result["status"] == "smoke_does_not_call_entrypoints", result


def test_variadic_keywords_and_literal_collection_arguments(tmp_path):
    result = execute(tmp_path, "def scale(*args, **kwargs):\n    return args\n", """
def run(common):
    assert common.scale([1, 2], mode='identity') == ([1, 2],)
    return True
""")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "scale", "scale([1, 2], mode='identity')")
    assert not _runtime_exercises_path(result, "scale", "scale([1, 3], mode='identity')")


def test_constructor_variadic_keywords_record_actual_mode(tmp_path):
    result = execute(tmp_path, "class Transform:\n    def __init__(self, **kwargs):\n        self.mode = kwargs['mode']\n", """
def run(common):
    assert common.Transform(mode='identity').mode == 'identity'
    return True
""", name="Transform", kind="class")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "Transform", "Transform(mode='identity')")
    assert not _runtime_exercises_path(result, "Transform", "Transform(mode='log')")


@pytest.mark.parametrize("preserve_signature", [False, True])
def test_shared_decorator_does_not_credit_another_method(tmp_path, preserve_signature):
    decoration = "@functools.wraps(fn)" if preserve_signature else ""
    library = f"""import functools
def decorate(fn):
    {decoration}
    def wrapped(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapped
class Transform:
    @decorate
    def identity(self, value):
        return value
    @decorate
    def log(self, value):
        raise AssertionError('log must not run')
"""
    result = execute(tmp_path, library, """
def run(common):
    obj = common.Transform()
    assert obj.identity(3) == 3
    return True
""", name="Transform", kind="class")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "Transform", "Transform.identity(3)")
    assert not _runtime_exercises_path(result, "Transform", "Transform.log")
    assert not _runtime_exercises_path(result, "Transform", "Transform.log(3)")


def test_shared_decorator_does_not_credit_another_function(tmp_path):
    library = """def decorate(fn):
    def wrapped(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapped
@decorate
def identity(mode):
    return mode
@decorate
def log(mode):
    raise AssertionError('log must not run')
"""
    result = execute(tmp_path, library, """
def run(common):
    assert common.identity(mode='identity') == 'identity'
    return True
""", entrypoints=[{"name": name, "kind": "function"} for name in ("identity", "log")])
    assert result["status"] == "smoke_does_not_call_entrypoints", result
    assert _runtime_exercises_path(result, "identity", "identity(mode='identity')")
    assert not _runtime_exercises_path(result, "log", "log(mode='identity')")


@pytest.mark.parametrize("kind", ["async", "generator", "async_generator"])
def test_resuming_frame_keeps_only_the_original_input_mode(tmp_path, kind):
    if kind == "async":
        library = """import asyncio
async def scale(mode):
    await asyncio.sleep(0)
    mode = 'log'
    await asyncio.sleep(0)
    return mode
"""
        smoke = "async def run(common):\n    assert await common.scale(mode='identity') == 'log'\n    return True\n"
    elif kind == "generator":
        library = "def scale(mode):\n    yield 1\n    mode = 'log'\n    yield 2\n"
        smoke = "def run(common):\n    assert list(common.scale(mode='identity')) == [1, 2]\n    return True\n"
    else:
        library = "async def scale(mode):\n    yield 1\n    mode = 'log'\n    yield 2\n"
        smoke = "async def run(common):\n    assert [x async for x in common.scale(mode='identity')] == [1, 2]\n    return True\n"
    result = execute(tmp_path, library, smoke)
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "scale", "scale(mode='identity')")
    assert not _runtime_exercises_path(result, "scale", "scale(mode='log')")


@pytest.mark.parametrize("call", ["common.Transform(3)", "common.Transform(value=3)", "common.Transform()"])
def test_constructor_positional_keyword_and_default_values_are_equivalent(tmp_path, call):
    result = execute(tmp_path, "class Transform:\n    def __init__(self, value=3):\n        self.value = value\n",
                     f"def run(common):\n    assert {call}.value == 3\n    return True\n",
                     name="Transform", kind="class")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "Transform", "Transform(3)")
    assert _runtime_exercises_path(result, "Transform", "Transform(value=3)")
    assert not _runtime_exercises_path(result, "Transform", "Transform(4)")


def test_constructor_records_mutable_argument_before_initialization(tmp_path):
    result = execute(tmp_path, "class Transform:\n    def __init__(self, values):\n        values.append(2)\n        self.values = values\n",
                     "def run(common):\n    assert common.Transform(values=[1]).values == [1, 2]\n    return True\n",
                     name="Transform", kind="class")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "Transform", "Transform([1])")
    assert not _runtime_exercises_path(result, "Transform", "Transform([1, 2])")


def test_separate_async_invocations_record_their_own_initial_parameters(tmp_path):
    result = execute(tmp_path, "import asyncio\nasync def scale(mode):\n    await asyncio.sleep(0)\n    return mode\n", """
async def run(common):
    assert await common.scale(mode='identity') == 'identity'
    assert await common.scale(mode='log') == 'log'
    return True
""")
    assert result["status"] == "ok", result
    assert _runtime_exercises_path(result, "scale", "scale(mode='identity')")
    assert _runtime_exercises_path(result, "scale", "scale(mode='log')")


@pytest.mark.parametrize("distinct_closures", [False, True])
def test_shared_factory_code_cannot_credit_another_function(tmp_path, distinct_closures):
    library = ("def make(offset):\n    def operation(value):\n        return value + offset\n    return operation\n"
               "first = make(1)\nsecond = make(2)\n" if distinct_closures else
               "def make():\n    def operation(value):\n        return value\n    return operation\n"
               "first = make()\nsecond = make()\n")
    wanted = 4 if distinct_closures else 3
    result = execute(tmp_path, library, f"def run(common):\n    assert common.first(3) == {wanted}\n    return True\n",
                     entrypoints=[{"name": name, "kind": "function"} for name in ("first", "second")])
    assert result["status"] == "smoke_does_not_call_entrypoints", result
    assert not _runtime_exercises_path(result, "second", "second(3)")
    assert _runtime_exercises_path(result, "first", "first(3)") is distinct_closures


@pytest.mark.parametrize("case", ["decorated_method", "async_resume", "constructor_keyword"])
def test_actual_observations_control_final_capability_publication(tmp_path, monkeypatch, case):
    from component_method.component_build.contracts import RepositoryContext
    from component_method.component_build.validation import service
    if case == "decorated_method":
        code = """def decorate(fn):
    def wrapped(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapped
class Transform:
    @decorate
    def identity(self, value):
        return value
    @decorate
    def log(self, value):
        raise AssertionError('log must not run')
"""
        smoke = "def run(common):\n    assert common.Transform().identity(3) == 3\n    return True\n"
        name, kind, path = "Transform", "class", "Transform.log"
    elif case == "async_resume":
        code = "import asyncio\nasync def scale(mode):\n    await asyncio.sleep(0)\n    mode = 'log'\n    await asyncio.sleep(0)\n    return mode\n"
        smoke = "async def run(common):\n    assert await common.scale(mode='identity') == 'log'\n    return True\n"
        name, kind, path = "scale", "function", "scale(mode='log')"
    else:
        code = "class Transform:\n    def __init__(self, value=3):\n        self.value = value\n"
        smoke = "def run(common):\n    assert common.Transform(value=3).value == 3\n    return True\n"
        name, kind, path = "Transform", "class", "Transform(3)"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text(code)
    member = {"file_id": "module.py", "unit_id": "module"}
    citation = {"file_id": "module.py", "line_start": 1, "line_end": len(code.splitlines()),
                "role": "interface_contract"}
    component = {"status": "draft_ready", "members": [member], "library": {"content": code},
                 "entrypoints": [{"name": name, "kind": kind}], "limitations": []}
    review = {"status": "confirmed", "reason": "Source-supported behavior", "confirmed_members": [member],
              "evidence": [{**citation, "claim": "Source implementation of the interface"}], "limitations": [],
              "artifact_review": {"status": "faithful", "reason": "Exact source copy"},
              "entrypoint_capabilities": [{"entrypoint": name, "path": path, "availability": "implemented",
                                           "contract": "Declared input", "example": path, "scope": "Declared input",
                                           "reason": "", "dependencies": [], "case_ids": ["case1"]}],
              "smoke_test": {"status": "ready", "reason": "Source contract", "cases": [
                  {"case_id": "case1", "entrypoint": name, "test_py": smoke, "sources": [citation]}]}}

    def host_runtime(**kwargs):
        kwargs["runtime_image"] = None
        return validate_callable_artifact(**kwargs)

    monkeypatch.setattr(service, "validate_callable_artifact", host_runtime)
    output = tmp_path / "output"
    result = service.validate_component(component_id=case, component=component,
                                        candidate_payload={"candidate": component},
                                        repository=RepositoryContext(repo_root=repo, runtime_image="fixture"),
                                        agent_runner=None, output_dir=output, review=review)
    should_publish = case == "constructor_keyword"
    assert result["case_results"]["case1"]["status"] == "ok", result
    assert result["status"] == ("validated" if should_publish else "failed"), result
    assert result["entrypoint_capabilities"][0]["validation_status"] == (
        "validated" if should_publish else "unverified")
    assert (output / "validated/common.py").exists() is should_publish
