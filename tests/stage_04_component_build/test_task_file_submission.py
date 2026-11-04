"""Check edited and newly created Python files before task submission."""

import subprocess

import pytest

from component_method.task_execution.runtime_support.check_edits import check_edits


@pytest.fixture
def repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "module.py").write_text("def original(): return 1\n")
    subprocess.run(["git", "add", "module.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "Initial"], cwd=tmp_path, check=True)
    return tmp_path


def test_changed_source_is_checked_without_execution(repository):
    (repository / "module.py").write_text("raise RuntimeError('must not run')\n")
    assert check_edits(repository) == []
    (repository / "module.py").write_text("def incomplete(:\n")
    assert any("module.py" in error for error in check_edits(repository))


def test_new_source_and_whitespace_are_checked(repository):
    (repository / "new.py").write_text("def incomplete(:\n")
    assert any("new.py" in error for error in check_edits(repository))
    (repository / "new.py").write_text("def good(): return 1\n")
    (repository / "module.py").write_text("def original(): return 2  \n")
    assert any("trailing whitespace" in error for error in check_edits(repository))
    subprocess.run(["git", "add", "module.py"], cwd=repository, check=True)
    assert any("trailing whitespace" in error for error in check_edits(repository))


def test_deleted_source_and_reference_bundle_are_not_treated_as_new_task_code(repository):
    (repository / "module.py").unlink()
    (repository / ".components").mkdir()
    (repository / ".components/reference.py").write_text("def partial(:\n")
    assert check_edits(repository) == []
