from copy import deepcopy

import pytest

from component_method.component_build.cache.review import dependency_snapshot, merge_review_dependencies


def test_valid_dependencies_merge_without_changing_original():
    manifest = {"complete": True, "files": ["module.py"], "search_scopes": ["pkg"]}
    original = deepcopy(manifest)
    merged = merge_review_dependencies(manifest, {"files": ["helper.py"], "search_scopes": ["."]})
    assert merged == {"complete": True, "files": ["helper.py", "module.py"],
                      "search_scopes": [".", "pkg"], "trace_accounting": "conservative_shell_scopes"}
    assert manifest == original


@pytest.mark.parametrize("field", ["files", "search_scopes"])
@pytest.mark.parametrize("malformed", [[{"scope": "pkg", "pattern": "name"}], None, "pkg", ["", 5], [["pkg"]]])
def test_malformed_dependencies_disable_cache_instead_of_crashing(tmp_path, field, malformed):
    (tmp_path / "module.py").write_text("pass\n")
    manifest = {"complete": True, "files": ["module.py"], "search_scopes": []}
    manifest[field] = malformed
    merged = merge_review_dependencies(manifest, {"files": ["module.py"], "search_scopes": ["."]})
    assert merged["complete"] is False
    assert field in merged["dependency_errors"][0]
    assert merged["search_scopes"] == ["."]
    assert merged["files"] == ["module.py"]
    assert dependency_snapshot(tmp_path, {}, {"validation_dependencies": merged}) is None


def test_unrecognized_trace_cannot_enable_review_cache():
    merged = merge_review_dependencies({"complete": True, "files": ["module.py"], "search_scopes": []}, None)
    assert merged["complete"] is False
    assert merged["trace_accounting"] == "unrecognized_trace"
