#!/usr/bin/env python3
"""Publish a migration component library directly from curated extraction.

The OS-Bench library publisher reads a reviewed-component summary.  Migration
preparation runs inside one task attempt and its source workspace is the task
repository, so the full independent-review loop is optional.  This publisher
keeps the deterministic admission gate (``curate``) and writes the same
artifact-v2 library shape used by retrieval and materialization:

* ``manifest.json`` (schema_version 8)
* ``metadata/<bundle>/artifact.json``
* ``audit/<bundle>.json`` with protocol contract and entrypoints
* ``components/<bundle>/...`` with the artifact files

It refuses to overwrite a non-empty library so a failed preparation can be
inspected instead of silently mixed with a later run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from component_method.workflow.experiment_common import PROJECT, ROOT, load_json, write_json


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet_responses(config: dict[str, Any]) -> list[tuple[str, Path]]:
    extraction_root = ROOT / "runs" / config["task_id"] / "extraction_v1"
    curated_root = extraction_root / "curated"
    curated_summary = curated_root / "summary.json"
    if curated_summary.is_file():
        summary = load_json(curated_summary)
        if summary.get("status") != "completed":
            raise RuntimeError("curated extraction admission is not complete")
        packets = [
            (packet["packet_id"], curated_root / "packets" / packet["packet_id"] / "extraction_response.json")
            for packet in summary.get("packets", [])
        ]
    else:
        raw_summary = extraction_root / "summary.json"
        if not raw_summary.is_file():
            raise RuntimeError("extraction has not produced a summary")
        summary = load_json(raw_summary)
        packets = [
            (packet_id, extraction_root / "packets" / packet_id / "extraction_response.json")
            for packet_id in summary.get("packet_ids", [])
        ]
    missing = [str(path) for _, path in packets if not path.is_file()]
    if missing:
        raise RuntimeError(f"extraction responses are missing: {missing[:5]}")
    return packets


def _entrypoints(artifact: Any) -> list[dict[str, Any]]:
    rows = []
    for entry in artifact.entrypoints:
        rows.append(
            {
                "name": entry.entrypoint_id,
                "kind": entry.kind,
                "qualified_name": entry.qualified_name,
                "signature": entry.signature,
                "purpose": entry.purpose,
            }
        )
    return rows


def publish(config: dict[str, Any]) -> dict[str, Any]:
    from component_method.component_build.validation.artifact_service import artifact_backend, artifact_of

    components: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for packet_id, response_path in _packet_responses(config):
        response = load_json(response_path)
        for component in response.get("components", []):
            if not isinstance(component, dict):
                continue
            component_id = component.get("component_id")
            if not isinstance(component_id, str) or not component_id:
                raise RuntimeError(f"component has no component_id in {packet_id}")
            if component_id in seen:
                raise RuntimeError(f"duplicate component_id across packets: {component_id}")
            seen.add(component_id)
            if component.get("status") not in {"draft_ready", "ready"}:
                raise RuntimeError(f"component is not draft_ready: {component_id}")
            if not isinstance(component.get("artifact"), dict):
                raise RuntimeError(f"migration component has no artifact: {component_id}")
            components.append((packet_id, component))
    if not components:
        raise RuntimeError("extraction produced no publishable components")

    library = ROOT / "outputs" / "full_library"
    if library.exists() and any(library.iterdir()):
        raise RuntimeError(f"preserving existing component library: {library}")
    library.mkdir(parents=True, exist_ok=True)

    records = []
    index = ["# Migration component library", ""]
    for number, (packet_id, component) in enumerate(components, 1):
        component_id = component["component_id"]
        artifact = artifact_of(component)
        backend = artifact_backend(artifact)
        bundle_id = f"component-{number:03d}"
        prefix = f"components/{bundle_id}"
        published = backend.materialize_component(artifact, library / prefix)
        descriptor = f"metadata/{bundle_id}/artifact.json"
        write_json(library / descriptor, artifact.to_json())
        readme = f"metadata/{bundle_id}/README.md"
        contract = component.get("protocol_contract") or {}
        audit = {
            "component_id": component_id,
            "name": component.get("name") or component_id,
            "summary": component.get("summary", ""),
            "capability": component.get("summary", ""),
            "members": component.get("members", []),
            "evidence": component.get("evidence", []),
            "limitations": component.get("limitations", []),
            "protocol_contract": contract,
            "protocol_status": "unreviewed_migration",
            "review_status": "not_run",
            "source_packet_id": packet_id,
            "language": artifact.language,
            "backend_id": artifact.backend_id,
            "entrypoints": _entrypoints(artifact),
            "loading_instructions": published.loading_instructions,
        }
        audit_path = f"audit/{bundle_id}.json"
        write_json(library / audit_path, audit)
        readme_lines = [
            f"# {audit['name']}",
            "",
            published.loading_instructions,
            "",
            audit["summary"],
            "",
            "## Entrypoints",
            "",
        ]
        readme_lines.extend(
            f"- `{entry['qualified_name']}` {entry['signature']}: {entry['purpose']}"
            for entry in audit["entrypoints"]
        )
        (library / readme).write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
        files = [f"{prefix}/{name}" for name in published.files]
        record = {
            "bundle_id": bundle_id,
            "language": artifact.language,
            "backend_id": artifact.backend_id,
            "library": descriptor,
            "artifact_file": descriptor,
            "component_root": prefix,
            "readme": readme,
            "audit_file": audit_path,
            "files": files,
        }
        names = [descriptor, readme, audit_path, *files]
        record["file_sha256"] = {name: _sha256(library / name) for name in names}
        records.append(record)
        index.extend(
            [
                f"## [{audit['name']}]({readme})",
                "",
                f"- Bundle ID: `{bundle_id}`",
                f"- Source packet: `{packet_id}`",
                f"- Language: `{artifact.language}`",
                f"- Entrypoints: {', '.join(entry['name'] for entry in audit['entrypoints'])}",
                "",
            ]
        )

    construction_key = hashlib.sha256(
        json.dumps(records, sort_keys=True).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": 8,
        "discovery_audit_status": "migration_direct_unreviewed",
        "method": "migration_source_region_direct_v1",
        "task_blind": False,
        "task_id": config.get("task_id"),
        "repository": config.get("repository", ""),
        "source_commit": config.get("source_commit", ""),
        "task_snapshot_key": None,
        "construction_key": construction_key,
        "component_count": len(records),
        "components_file": "INDEX.md",
        "libraries": [record["library"] for record in records],
        "consumer_metadata_schema": 2,
        "components": records,
    }
    write_json(library / "manifest.json", manifest)
    (library / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    (library / "README.md").write_text(
        "# Migration component library\n\n"
        "Built from the current attempt's source workspace by the migration "
        "source-scan/extraction path. Deterministic admission only; the "
        "independent review loop was not run.\n",
        encoding="utf-8",
    )
    return {
        "library": str(library),
        "component_count": len(records),
        "construction_key": construction_key,
    }


def main() -> None:
    config = load_json(ROOT / "config.json")
    print(json.dumps(publish(config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()