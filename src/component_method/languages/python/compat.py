"""Explicit, reversible conversion of frozen Python records to v2 contracts."""

from copy import deepcopy
from typing import Any

from component_method.languages.contracts import (
    ArtifactFile, ComponentArtifact, Entrypoint, SmokeCase, SourceUnit,
)


def legacy_unit(unit: SourceUnit) -> dict[str, str]:
    if unit.backend_id != "python@1" or "legacy_unit_id" not in unit.metadata:
        raise ValueError("unit has no Python v1 representation")
    return {"file_id": unit.file_id, "unit_id": unit.metadata["legacy_unit_id"],
            "source_code": unit.source_code}


def artifact_from_legacy(component: dict[str, Any]) -> ComponentArtifact:
    library = component.get("library")
    if not isinstance(library, dict) or not isinstance(library.get("content"), str):
        raise ValueError("legacy artifact requires hydrated library.content")
    entries = component.get("entrypoints", [])
    if not isinstance(entries, list):
        raise ValueError("legacy entrypoints must be a list")
    converted = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("legacy entrypoint requires a name")
        converted.append(Entrypoint(
            entry.get("kind", "function"), entry["name"], entry.get("signature", ""),
            entry.get("purpose", ""), {"legacy": deepcopy(entry)},
        ))
    return ComponentArtifact(
        "python", "python@1", (ArtifactFile("component.py", library["content"]),),
        tuple(converted), {"backend": "python", "artifact_type": "module"},
        {"legacy_component": deepcopy(component)},
    )


def artifact_to_legacy(artifact: ComponentArtifact) -> dict[str, Any]:
    if artifact.backend_id != "python@1" or len(artifact.files) != 1:
        raise ValueError("only single-file Python artifacts have a v1 representation")
    if "legacy_component" not in artifact.metadata:
        raise ValueError("artifact has no lossless legacy representation")
    component = deepcopy(artifact.metadata["legacy_component"])
    component["library"]["content"] = artifact.files[0].content
    entries = [
        {**deepcopy(entry.metadata.get("legacy", {})),
         "kind": entry.kind, "name": entry.qualified_name,
         **({"signature": entry.signature} if entry.signature else {}),
         **({"purpose": entry.purpose} if entry.purpose else {})}
        for entry in artifact.entrypoints
    ]
    if entries or "entrypoints" in component:
        component["entrypoints"] = entries
    return component


def smoke_from_legacy(case: dict[str, Any]) -> SmokeCase:
    if not isinstance(case.get("test_py"), str):
        raise ValueError("legacy smoke case requires hydrated test_py")
    return SmokeCase(
        case.get("case_id", "case-1"), case.get("entrypoint", ""),
        (ArtifactFile("smoke.py", case["test_py"], "test"),),
        tuple(deepcopy(case.get("expected_paths", []))),
        tuple(deepcopy(case.get("sources", []))),
        {"legacy_case": deepcopy(case)},
    )


def smoke_to_legacy(case: SmokeCase) -> dict[str, Any]:
    if "legacy_case" not in case.metadata or len(case.files) != 1:
        raise ValueError("smoke case has no lossless legacy representation")
    result = deepcopy(case.metadata["legacy_case"])
    result["test_py"] = case.files[0].content
    return result
