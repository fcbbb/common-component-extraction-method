"""Resolve component environment variables through the published backends."""

import json
from pathlib import Path

from .registry import default_registry


def bundle_environment(bundle, *, container_root="/testbed/component_bundle", repository_root="/testbed"):
    if bundle is None:
        from .python.task_runtime import legacy_environment

        return legacy_environment(repository_root, False)
    manifest_path = Path(bundle) / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    if manifest.get("schema_version") != 8:
        from .python.task_runtime import legacy_environment

        return legacy_environment(repository_root, True, container_root)
    result = {"COMPONENT_BUNDLE": container_root, "PYTHONPATH": repository_root}
    registry = default_registry()
    for record in manifest["components"]:
        backend = registry.resolve({"language": record["language"]}).single()
        if backend.backend_id != record["backend_id"]:
            raise ValueError("published component backend version is not installed")
        from .contracts import relative_path

        path = Path(container_root) / relative_path(record["component_root"])
        for key, value in backend.bundle_environment(path).items():
            if key == "COMPONENT_BUNDLE":
                continue
            result[key] = ":".join(dict.fromkeys(filter(None, [result.get(key), value])))
    return result
