"""Publish immutable multi-file artifacts and select identity-preserving subsets."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from component_method.component_build.validation.artifact_service import artifact_backend, artifact_of, extraction_record
from component_method.languages.contracts import contained_path, stable_digest


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_artifact(component, validation, library, bundle_id):
    artifact = artifact_of(component)
    backend = artifact_backend(artifact)
    if validation.get("status") != "validated":
        raise ValueError("artifact publication requires runtime validation")
    if validation.get("artifact_sha256") != stable_digest(artifact.to_json()):
        raise ValueError("artifact changed after runtime validation")
    if validation.get("component_sha256") != stable_digest(component):
        raise ValueError("component metadata changed after validation")
    identity = validation.get("backend_identity", {})
    current = backend.identity().to_json()
    for field in ("language", "backend_version", "parser", "parser_version", "implementation_sha256"):
        if identity.get(field) != current[field]:
            raise ValueError("backend changed after validation")
    review = validation.get("commonality_review", {})
    if (review.get("status") != "confirmed" or review.get("artifact_review", {}).get("status") != "faithful"
            or review.get("protocol_contract_review", {}).get("status") not in {"confirmed", "confirmed_with_warnings"}):
        raise ValueError("review does not permit publication")
    prefix = f"components/{bundle_id}"
    root = contained_path(library, prefix)
    published = backend.materialize_component(artifact, root)
    descriptor = f"metadata/{bundle_id}/artifact.json"
    write_json(contained_path(library, descriptor), artifact.to_json())
    capabilities = validation.get("entrypoint_capabilities", [])
    statuses = {cap["entrypoint"]: cap["validation_status"] for cap in capabilities}
    audit = {**{k: component[k] for k in ("component_id", "name", "summary", "members", "evidence", "limitations", "protocol_contract") if k in component},
             "language": artifact.language, "backend_id": artifact.backend_id, "backend_identity": identity,
             "entrypoints": [{**e.to_json(), "name": e.entrypoint_id,
                              "validation_status": statuses.get(e.entrypoint_id, "unverified")} for e in artifact.entrypoints],
             "entrypoint_capabilities": capabilities, "artifact_sha256": validation["artifact_sha256"],
             "source_sha256": validation.get("source_sha256", {}), "protocol_status": review["protocol_contract_review"]["status"],
             "loading_instructions": published.loading_instructions}
    record = {"bundle_id": bundle_id, "language": artifact.language, "backend_id": artifact.backend_id,
              "backend_identity": identity, "library": descriptor, "artifact_file": descriptor,
              "component_root": prefix, "readme": f"metadata/{bundle_id}/README.md", "audit_file": f"audit/{bundle_id}.json",
              "files": [f"{prefix}/{name}" for name in published.files]}
    write_json(contained_path(library, record["audit_file"]), audit)
    readme = ["# " + str(component.get("name") or bundle_id), "", published.loading_instructions, "",
              str(component.get("summary", "")), "", "## Entrypoints", ""]
    readme += [f"- `{e.qualified_name}` {e.signature}: {statuses.get(e.entrypoint_id, 'unverified')}" for e in artifact.entrypoints]
    contained_path(library, record["readme"]).write_text("\n".join(readme) + "\n", encoding="utf-8")
    record["file_sha256"] = {name: file_digest(contained_path(library, name)) for name in
                             [descriptor, record["readme"], record["audit_file"], *record["files"]]}
    return record


def publish_artifact_library(records, destination, *, repository="", source_commit="", manifest_metadata=None):
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"preserving existing library: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".artifacts-", dir=destination.parent))
    staging.chmod(0o755)
    try:
        entries = [publish_artifact(record["component"], record["validation"], staging, f"component-{i:03d}")
                   for i, record in enumerate(records, 1)]
        manifest = {"schema_version": 8, "repository": repository, "source_commit": source_commit,
                    "component_count": len(entries), "components": entries, "components_file": "INDEX.md",
                    "libraries": [e["library"] for e in entries], "construction_key": stable_digest(entries),
                    "task_blind": True}
        manifest.update(manifest_metadata or {})
        write_json(staging / "manifest.json", manifest)
        (staging / "INDEX.md").write_text("# Component index\n\n" + "\n".join(
            f"- [{r['bundle_id']}]({r['readme']}) ({r['language']})" for r in entries) + "\n")
        (staging / "README.md").write_text("# Component library\n\nSee INDEX.md for source files and loading instructions.\n")
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def select_artifact_bundle(source, selection, destination):
    if destination.exists():
        raise FileExistsError(f"preserving existing bundle: {destination}")
    manifest = json.loads((source / "manifest.json").read_text())
    selected = set(selection["selected_bundle_ids"])
    records = [r for r in manifest["components"] if r["bundle_id"] in selected]
    if {r["bundle_id"] for r in records} != selected:
        raise ValueError("selection names an unknown component")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".selected-artifacts-", dir=destination.parent))
    staging.chmod(0o755)
    try:
        for record in records:
            required = {record["library"], record["readme"], record["audit_file"], *record["files"]}
            if set(record["file_sha256"]) != required:
                raise ValueError("artifact digest manifest does not cover every published file")
            for name, expected in record["file_sha256"].items():
                path = contained_path(source, name)
                if file_digest(path) != expected:
                    raise ValueError(f"published artifact changed: {name}")
                target = contained_path(staging, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        write_json(staging / "selection.json", selection)
        (staging / "README.md").write_text("# Selected component library\n\nSee INDEX.md for loading instructions.\n")
        (staging / "INDEX.md").write_text("# Selected components\n\n" + "\n".join(
            f"- [{r['bundle_id']}]({r['readme']}) ({r['language']})" for r in records) + "\n")
        write_json(staging / "manifest.json", {**manifest, "components": records, "component_count": len(records),
                   "libraries": [r["library"] for r in records], "selected_bundle_ids": sorted(selected),
                   "parent_construction_key": manifest["construction_key"], "construction_key": stable_digest(records),
                   "selection_method": "validated_task_retrieval_subset"})
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination
