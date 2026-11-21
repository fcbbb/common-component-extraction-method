#!/usr/bin/env python3
"""Publish a component library without running the review gate.

This is the explicit ``publish_mode = "unreviewed"`` path.  It publishes the
components frozen by ``build`` after deterministic curation, marks every audit
record as unreviewed, and records that fact in the manifest so downstream
consumers can tell the difference.  It never overwrites a non-empty library.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from component_method.workflow.experiment_common import (
    PROJECT,
    ROOT,
    load_json,
    render_component_readme,
    sha256,
    write_json,
)


def _artifact_audit(component: dict, artifact, published, packet_id: str) -> dict:
    contract = component.get("protocol_contract") or {}
    return {
        "component_id": component.get("component_id"),
        "name": component.get("name") or component.get("component_id"),
        "summary": component.get("summary", ""),
        "capability": component.get("summary", ""),
        "members": component.get("members", []),
        "evidence": component.get("evidence", []),
        "limitations": component.get("limitations", []),
        "protocol_contract": contract,
        "protocol_status": "unreviewed",
        "review_status": "not_run",
        "artifact_review": None,
        "source_packet_id": packet_id,
        "language": artifact.language,
        "backend_id": artifact.backend_id,
        "entrypoints": [
            {
                "name": entry.entrypoint_id,
                "kind": entry.kind,
                "qualified_name": entry.qualified_name,
                "signature": entry.signature,
                "purpose": entry.purpose,
            }
            for entry in artifact.entrypoints
        ],
        "loading_instructions": published.loading_instructions,
    }


def main() -> None:
    config = load_json(ROOT / "config.json")
    frozen_path = ROOT / "inputs" / "frozen_components.json"
    frozen = load_json(frozen_path)
    records_in = frozen.get("records")
    if not isinstance(records_in, list) or not records_in:
        raise RuntimeError("frozen components are empty; run the build block first")

    library = ROOT / "outputs" / "full_library"
    if library.exists() and any(library.iterdir()):
        raise RuntimeError(f"preserving existing component library: {library}")
    library.mkdir(parents=True, exist_ok=True)

    manifest_records = []
    mapping = []
    construction_records = []
    index = ["# Unreviewed component index", ""]
    has_artifact = False
    for number, record in enumerate(records_in, 1):
        component = record.get("component")
        if not isinstance(component, dict):
            raise RuntimeError(f"frozen record has no component: {record.get('component_id')}")
        component_id = component.get("component_id") or record.get("component_id")
        packet_id = record.get("source_packet_id", "")
        bundle_id = f"component-{number:03d}"
        artifact = component.get("artifact")

        if isinstance(artifact, dict):
            has_artifact = True
            from component_method.component_build.validation.artifact_service import artifact_backend, artifact_of

            parsed = artifact_of(component)
            backend = artifact_backend(parsed)
            prefix = f"components/{bundle_id}"
            published = backend.materialize_component(parsed, library / prefix)
            descriptor = f"metadata/{bundle_id}/artifact.json"
            write_json(library / descriptor, parsed.to_json())
            readme = f"metadata/{bundle_id}/README.md"
            audit = _artifact_audit(component, parsed, published, packet_id)
            audit_path = f"audit/{bundle_id}.json"
            write_json(library / audit_path, audit)
            files = [f"{prefix}/{name}" for name in published.files]
            manifest_record = {
                "bundle_id": bundle_id,
                "language": parsed.language,
                "backend_id": parsed.backend_id,
                "library": descriptor,
                "artifact_file": descriptor,
                "component_root": prefix,
                "readme": readme,
                "audit_file": audit_path,
                "files": files,
            }
            manifest_record["file_sha256"] = {
                name: sha256(library / name)
                for name in [descriptor, readme, audit_path, *files]
            }
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
        else:
            content = (component.get("library") or {}).get("content")
            if not isinstance(content, str):
                raise RuntimeError(f"component has neither artifact nor library content: {component_id}")
            bundle_root = library / "components" / bundle_id
            bundle_root.mkdir(parents=True)
            (bundle_root / "component.py").write_text(content, encoding="utf-8")
            readme = f"components/{bundle_id}/README.md"
            (library / readme).write_text(render_component_readme(component), encoding="utf-8")
            audit = {
                "component_id": component_id,
                "name": component.get("name"),
                "capability": component.get("summary"),
                "entrypoints": component.get("entrypoints", []),
                "members": component.get("members", []),
                "evidence": component.get("evidence", []),
                "limitations": component.get("limitations", []),
                "protocol_contract": component["protocol_contract"],
                "protocol_status": "unreviewed",
                "review_status": "not_run",
                "artifact_review": None,
                "source_packet_id": packet_id,
            }
            audit_path = f"audit/{bundle_id}.json"
            write_json(library / audit_path, audit)
            manifest_record = {
                "bundle_id": bundle_id,
                "library": f"components/{bundle_id}/component.py",
                "readme": readme,
                "audit_file": audit_path,
            }

        manifest_records.append(manifest_record)
        mapping.append(
            {
                "bundle_id": bundle_id,
                "component_id": component_id,
                "source_packet_id": packet_id,
                "protocol_status": "unreviewed",
            }
        )
        construction_records.append({"component_id": component_id, "component_sha256": sha256(library / manifest_record["library"])})
        index.extend(
            [
                f"## [{component.get('name') or component_id}]({readme})",
                "",
                f"- Bundle ID: `{bundle_id}`",
                f"- Review status: `not_run`",
                "",
            ]
        )

    (library / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    (library / "README.md").write_text(
        "# Unreviewed component library\n\n"
        "Components passed deterministic curation but not the independent review "
        "gate. Treat them as drafts.\n",
        encoding="utf-8",
    )
    construction_payload = {
        "frozen_components_sha256": sha256(frozen_path),
        "publish_mode": "unreviewed",
        "records": construction_records,
    }
    construction_key = hashlib.sha256(
        json.dumps(construction_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    write_json(
        library / "manifest.json",
        {
            "schema_version": 8 if has_artifact else 7,
            "discovery_audit_status": "task_blind_unreviewed",
            "review_status": "not_run",
            "method": "ffsim_focus_context_protocol_contract_unreviewed",
            "repository": config.get("repository"),
            "source_commit": config.get("source_commit"),
            "task_snapshot_key": None,
            "construction_key": construction_key,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "component_count": len(manifest_records),
            "components_file": "INDEX.md",
            "libraries": [item["library"] for item in manifest_records],
            "consumer_metadata_schema": 2,
            "components": manifest_records,
        },
    )
    write_json(
        ROOT / "outputs" / "FULL_BUNDLE_MAP.json",
        {
            "schema": "ffsim-full-unreviewed-library-map-v1",
            "construction_key": construction_key,
            "component_count": len(mapping),
            "records": mapping,
        },
    )
    print(
        json.dumps(
            {
                "library": str(library.relative_to(PROJECT)),
                "component_count": len(manifest_records),
                "construction_key": construction_key,
                "review_status": "not_run",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()