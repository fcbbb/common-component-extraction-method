import json
import os
import subprocess
import sys

import pytest

from component_method.languages.task_environment import bundle_environment


def test_python_bundle_imports_repository_dependencies_from_unrelated_directory(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "repo_support.py").write_text("VALUE = 7\n")
    bundle = tmp_path / "bundle"
    records = []
    for index, module in enumerate(("first_component", "second_component"), start=1):
        component_root = f"components/component-{index:03d}"
        component = bundle / component_root
        component.mkdir(parents=True)
        (component / f"{module}.py").write_text("from repo_support import VALUE\n")
        records.append({"language": "python", "backend_id": "python@1", "component_root": component_root})
    (bundle / "manifest.json").write_text(json.dumps({"schema_version": 8, "components": records}))
    environment = bundle_environment(bundle, container_root=str(bundle), repository_root=str(repository))
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    process = subprocess.run(
        [sys.executable, "-S", "-c",
         "import first_component, second_component; "
         "assert first_component.VALUE == second_component.VALUE == 7"],
        cwd=unrelated, env={**os.environ, **environment}, capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stderr
    assert environment["PYTHONPATH"].split(":") == [str(repository)] + [
        str(bundle / record["component_root"]) for record in records
    ]
    container_environment = bundle_environment(bundle)
    assert container_environment["PYTHONPATH"] == (
        "/testbed:/testbed/component_bundle/components/component-001:"
        "/testbed/component_bundle/components/component-002"
    )
    assert all(str(tmp_path) not in value for value in container_environment.values())


@pytest.mark.parametrize("schema_version", [None, 7, 8])
def test_empty_bundles_keep_repository_import_path(tmp_path, schema_version):
    bundle = None
    if schema_version is not None:
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "manifest.json").write_text(json.dumps({"schema_version": schema_version, "components": []}))
    environment = bundle_environment(bundle, repository_root="/workspace", container_root="/components")
    assert environment["PYTHONPATH"] == ("/workspace:/components" if schema_version == 7 else "/workspace")
