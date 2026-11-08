#!/usr/bin/env python3
"""Publish every automatically review-approved FFSIM component without task-aware screening."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from component_method.workflow.experiment_common import (
    PROJECT,
    ROOT,
    load_json,
    render_component_readme,
    sha256,
    write_json,
)


def main() -> None:
    config = load_json(ROOT / "config.json")
    frozen_path = ROOT / "inputs" / "frozen_components.json"
    frozen = load_json(frozen_path)
    records_by_id = {record["component_id"]: record for record in frozen["records"]}
    review_root = ROOT / "runs" / config["task_id"] / "review_v1"
    summary = load_json(review_root / "summary.json")
    if summary.get("status") != "completed":
        raise RuntimeError("review is not complete")
    component_ids = summary["published_components"]
    if not component_ids:
        raise RuntimeError("review produced no publishable components")
    from component_method.component_build.validation.artifact_service import extraction_record

    formats = {"artifact" in extraction_record(load_json(
        review_root / "components" / component_id / "effective_component.json")) for component_id in component_ids}
    if len(formats) > 1:
        raise ValueError("publish historical records and artifact-v2 records as separate libraries")

    library = ROOT / "outputs" / "full_library"
    if library.exists() and any(library.iterdir()):
        raise RuntimeError(f"preserving existing component library: {library}")
    library.mkdir(parents=True, exist_ok=True)

    manifest_records = []
    mapping = []
    index = ["# Full reviewed FFSIM component index", ""]
    construction_records = []
    for number, component_id in enumerate(component_ids, 1):
        source_record = records_by_id[component_id]
        component_root = review_root / "components" / component_id
        result = load_json(component_root / "result.json")
        if not result.get("publishable"):
            raise RuntimeError(f"component is not publishable: {component_id}")
        component_path = component_root / "effective_component.json"
        review_path = component_root / "final_review.json"
        component = load_json(component_path)
        review = load_json(review_path)
        bundle_id = f"component-{number:03d}"
        if "artifact" in extraction_record(component):
            from component_method.library_publish.artifacts import publish_artifact

            manifest_record = publish_artifact(component, result["validation"], library, bundle_id)
            manifest_records.append(manifest_record)
            mapping.append({"bundle_id": bundle_id, "component_id": component_id,
                            "source_packet_id": source_record["source_packet_id"],
                            "protocol_status": review["protocol_contract_review"]["status"]})
            construction_records.append({"component_id": component_id,
                                         "component_sha256": sha256(component_path), "review_sha256": sha256(review_path),
                                         "validation_sha256": sha256(component_root / "runtime_validation/validation.json")})
            index.extend([f"## [{component.get('name') or component_id}]({manifest_record['readme']})", "",
                          f"- Language: `{manifest_record['language']}`", ""])
            continue
        bundle_root = library / "components" / bundle_id
        bundle_root.mkdir(parents=True)
        (bundle_root / "component.py").write_text(
            component["library"]["content"], encoding="utf-8"
        )
        (bundle_root / "README.md").write_text(
            render_component_readme(component), encoding="utf-8"
        )
        audit = {
            "component_id": component_id,
            "name": component.get("name"),
            "capability": component.get("summary"),
            "entrypoints": component.get("entrypoints", []),
            "members": component.get("members", []),
            "evidence": component.get("evidence", []),
            "limitations": component.get("limitations", []),
            "protocol_contract": component["protocol_contract"],
            "protocol_status": review["protocol_contract_review"]["status"],
            "review_status": review["status"],
            "artifact_review": review.get("artifact_review"),
            "source_packet_id": source_record["source_packet_id"],
            "component_source": str(component_path.relative_to(PROJECT)),
            "component_source_sha256": sha256(component_path),
            "review_source": str(review_path.relative_to(PROJECT)),
            "review_source_sha256": sha256(review_path),
        }
        audit_path = library / "audit" / f"{bundle_id}.json"
        write_json(audit_path, audit)
        manifest_record = {
            "bundle_id": bundle_id,
            "library": f"components/{bundle_id}/component.py",
            "readme": f"components/{bundle_id}/README.md",
            "audit_file": f"audit/{bundle_id}.json",
        }
        manifest_records.append(manifest_record)
        mapping.append(
            {
                "bundle_id": bundle_id,
                "component_id": component_id,
                "source_packet_id": source_record["source_packet_id"],
                "protocol_status": audit["protocol_status"],
            }
        )
        construction_records.append(
            {
                "component_id": component_id,
                "component_sha256": sha256(component_path),
                "review_sha256": sha256(review_path),
            }
        )
        index.extend(
            [
                f"## [{component.get('name') or component_id}]({manifest_record['readme']})",
                "",
                f"- Bundle ID: `{bundle_id}`",
                f"- Internal ID: `{component_id}`",
                f"- Protocol status: `{audit['protocol_status']}`",
                f"- Capability family: `{component['protocol_contract']['capability_family']}`",
                f"- Extension trigger: {component['protocol_contract']['extension_trigger']}",
                f"- Boundary: {component['protocol_contract']['boundary']}",
                "",
            ]
        )

    (library / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    (library / "README.md").write_text(
        "# Full reviewed FFSIM component library\n\n"
        "Every automatically publishable component is included without task-aware screening "
        "or cross-packet merging.\n",
        encoding="utf-8",
    )
    construction_payload = {
        "frozen_components_sha256": sha256(frozen_path),
        "review_summary_sha256": sha256(review_root / "summary.json"),
        "records": construction_records,
    }
    construction_key = hashlib.sha256(
        json.dumps(construction_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    write_json(
        library / "manifest.json",
        {
            "schema_version": 8 if any("artifact_file" in r for r in manifest_records) else 7,
            "discovery_audit_status": "task_blind_reviewed_unscreened",
            "method": "ffsim_focus_context_protocol_contract_audit_gate_v2",
            "repository": config["repository"],
            "source_commit": config["source_commit"],
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
            "schema": "ffsim-full-reviewed-library-map-v1",
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
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
