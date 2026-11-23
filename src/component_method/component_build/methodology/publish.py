"""Publish reviewed transformations as a `methodology-1` library.

The output is the same contract the existing retrieval path already consumes:
``manifest.json`` (kind=methodology), ``INDEX.md``, ``SELECTION.md`` and one
``components/<bundle>/README.md`` + ``component.json`` per transformation.
No code, no target-project paths, no gold files.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    component_metadata,
    digest,
    leakage_findings,
    render_readme,
    validate_transformation,
)
from .corpus import corpus_digest, load_corpus

LIBRARY_SCHEMA = "methodology-1"
LOCK_SCHEMA = "methodology-library-lock-v1"
GENERATED_BY = "component_method.component_build.methodology.publish"
DEFAULT_HELD_OUT = {"poco", "nginx", "curl", "opencv"}


def _held_out(corpus: Any) -> set[str]:
    """Held-out repositories of this corpus, falling back to the V3 default."""
    policy = (getattr(corpus, "index", None) or {}).get("policy") or {}
    values = (
        policy["held_out_repos"] if "held_out_repos" in policy else DEFAULT_HELD_OUT
    )
    return {str(item).lower() for item in values}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_id(transformation_id: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", transformation_id).strip("-") or "transformation"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _index_markdown(components: list[dict[str, Any]]) -> str:
    lines = [
        "# Transformation library index",
        "",
        "Methodology components extracted from completed migrations. They are",
        "project-agnostic: rules, semantic deltas, pitfalls and verification, not",
        "implementations.",
        "",
        "## How to use",
        "",
        "1. Identify which layer the task must rebuild.",
        "2. Read every component whose `capability` matches that layer.",
        "3. Treat the workspace contract as authoritative; the component only",
        "   supplies the mapping procedure, deltas and pitfalls.",
        "",
        "## Components",
        "",
        "| ID | Component | Capability | Use when |",
        "|---|---|---|---|",
    ]
    for component in components:
        when = " ".join(component["when_to_use"].split())
        if len(when) > 140:
            when = when[:137].rstrip() + "..."
        lines.append(
            f"| `{component['bundle_id']}` | "
            f"[{component['title']}](components/{component['bundle_id']}/README.md) | "
            f"`{component['capability']}` | {when} |"
        )
    lines.extend(
        [
            "",
            "## What these components do not contain",
            "",
            "- No target-project file list, symbol list or line references.",
            "- No implementation snippets intended for copying.",
            "- No test names or evaluator commands.",
            "- No current-task gold.",
            "",
        ]
    )
    return "\n".join(lines)


def _selection_markdown(components: list[dict[str, Any]]) -> str:
    lines = [
        "# Selection guide",
        "",
        "This is a transformation library: it records how comparable migrations were",
        "done, where they fail, and how to verify the result. It does not contain the",
        "current task's implementation.",
        "",
        "## Select before you write code",
        "",
        "1. Read the task statement and the workspace contract.",
        "2. Identify which layer is missing, then consult the component list.",
        "3. Keep the components whose `When to use` matches the task.",
        "4. Use a component when it changes a decision or prevents a known failure.",
        "",
        "## Mapping the task to components",
        "",
        "| If the task must rebuild... | Read |",
        "|---|---|",
    ]
    for component in components:
        lines.append(
            f"| {component['title']} (`{component['capability']}`) | "
            f"`{component['bundle_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Using a component",
            "",
            "- Treat the workspace headers and callers as the contract.",
            "- Map each rule to the current names and semantics, in the current code.",
            "- Apply the verification section to the current task's behavior.",
            "- Use `Boundary` to decide when the method stops applying.",
            "",
        ]
    )
    return "\n".join(lines)


def _publishable(
    entries: list[dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Only an explicit ``publish`` verdict reaches the library."""
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in entries:
        transformation_id = entry["transformation_id"]
        review = reviews.get(transformation_id)
        if review is None:
            skipped.append(
                {
                    "transformation_id": transformation_id,
                    "reason": "no review; the component was never judged",
                }
            )
            continue
        verdict = review.get("verdict")
        if verdict != "publish":
            reason = {
                "discard": "discarded by review: no reusable value",
                "rework": "rework verdict was not finalized",
                "invalid": "review or finalize output was invalid",
            }.get(str(verdict), f"unknown verdict {verdict!r}")
            skipped.append(
                {"transformation_id": transformation_id, "reason": reason}
            )
            continue
        selected.append({**entry, "review": review})
    return selected, skipped


def publish(
    history_root: Path,
    curated_root: Path,
    review_root: Path | None,
    destination: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    corpus = load_corpus(history_root)
    curated_root = curated_root.expanduser().resolve()
    destination = destination.expanduser().resolve()
    entries_path = curated_root / "transformations.json"
    if not entries_path.is_file():
        raise RuntimeError(f"curated transformations are missing: {entries_path}")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("curation produced no transformations to publish")

    reviews: dict[str, dict[str, Any]] = {}
    if review_root is not None:
        review_root = review_root.expanduser().resolve()
        if not review_root.is_dir():
            raise RuntimeError(f"review directory is missing: {review_root}")
        for path in sorted(review_root.glob("*/review.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("transformation_id"), str):
                reviews[value["transformation_id"]] = value

    selected, skipped = _publishable(entries, reviews)
    per_example: dict[str, int] = {}
    for entry in selected:
        per_example[entry["example_id"]] = per_example.get(entry["example_id"], 0) + 1
    repeated = {key: value for key, value in per_example.items() if value > 1}
    if repeated:
        raise RuntimeError(
            "an example yields exactly one component; repeated: "
            f"{repeated}"
        )
    if not selected:
        # Every component was explicitly discarded; an empty library is the
        # honest result.  Any other reason for an empty set is a gate bug.
        unjustified = [
            item for item in skipped
            if "discarded by review" not in item["reason"]
        ]
        if unjustified:
            raise RuntimeError(
                "no transformation passed the publication gate; "
                f"skipped={unjustified[:5]}"
            )

    if destination.exists() and any(destination.iterdir()):
        prior = destination / "manifest.json"
        owned = False
        if prior.is_file():
            try:
                owned = json.loads(prior.read_text(encoding="utf-8")).get(
                    "generated_by"
                ) == GENERATED_BY
            except json.JSONDecodeError:
                owned = False
        if not force or not owned:
            raise RuntimeError(
                f"preserving existing library: {destination}; pass --force to replace "
                "a library generated by this publisher"
            )
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    selected.sort(key=lambda item: (item["capability"], item["transformation_id"]))
    used: set[str] = set()
    published: list[dict[str, Any]] = []
    component_digests: list[dict[str, Any]] = []
    for entry in selected:
        transformation = entry["transformation"]
        example = corpus.example(entry["example_id"]).metadata
        errors = validate_transformation(transformation, example=example)
        if errors:
            raise RuntimeError(
                f"{entry['transformation_id']} is no longer publishable: {errors}"
            )
        bundle_id = _bundle_id(entry["transformation_id"], used)
        metadata = component_metadata(
            transformation,
            bundle_id=bundle_id,
            review=entry.get("review"),
            input_digest=entry["entry_digest"],
        )
        readme = render_readme(metadata)
        component_root = destination / "components" / bundle_id
        component_root.mkdir(parents=True, exist_ok=True)
        (component_root / "README.md").write_text(readme + "\n", encoding="utf-8")
        _write_json(component_root / "component.json", metadata)
        published.append(metadata)
        component_digests.append(
            {
                "bundle_id": bundle_id,
                "transformation_id": entry["transformation_id"],
                "capability": metadata["capability"],
                "provenance": metadata["provenance"],
                "review_verdict": (entry.get("review") or {}).get("verdict", "missing"),
                "component_sha256": digest(metadata),
                "readme_sha256": _sha256(component_root / "README.md"),
            }
        )

    manifest = {
        "schema_version": LIBRARY_SCHEMA,
        "kind": "methodology",
        "library_id": corpus.index.get("library_id") or "transformation-library",
        "version": 1,
        "generated_by": GENERATED_BY,
        "generated_at": _now(),
        "component_count": len(published),
        "components_file": "INDEX.md",
        "selection_file": "SELECTION.md",
        "components": [
            {
                "bundle_id": item["bundle_id"],
                "title": item["title"],
                "capability": item["capability"],
                "library": f"components/{item['bundle_id']}/README.md",
                "readme": f"components/{item['bundle_id']}/README.md",
                "metadata": f"components/{item['bundle_id']}/component.json",
            }
            for item in published
        ],
    }
    _write_json(destination / "manifest.json", manifest)
    (destination / "INDEX.md").write_text(_index_markdown(published), encoding="utf-8")
    (destination / "SELECTION.md").write_text(
        _selection_markdown(published), encoding="utf-8"
    )
    lock = {
        "schema": LOCK_SCHEMA,
        "library_id": manifest["library_id"],
        "version": manifest["version"],
        "created_at": _now(),
        "history_root": str(corpus.root),
        "history_digest": corpus_digest(corpus.root),
        "curation_sha256": _sha256(entries_path),
        "review_root": str(review_root) if review_root else None,
        "publication": {"status": "published", "generated_by": GENERATED_BY},
        "policy": {
            "publication_gate": "review verdict == publish",
            "held_out_projects": sorted(_held_out(corpus)),
        },
        "components": component_digests,
    }
    _write_json(destination / "library_lock.json", lock)
    return {
        "schema": "methodology-publication-v1",
        "library": str(destination),
        "component_count": len(published),
        "skipped": skipped,
        "components": [
            {"bundle_id": item["bundle_id"], "capability": item["capability"]}
            for item in published
        ],
        "history_digest": lock["history_digest"],
    }


def verify_library(destination: Path, *, history_root: Path | None = None) -> dict[str, Any]:
    destination = destination.expanduser().resolve()
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"library manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != LIBRARY_SCHEMA or manifest.get("kind") != "methodology":
        raise RuntimeError("library is not a methodology-1 manifest")
    components = manifest.get("components") or []
    if manifest.get("component_count") != len(components):
        raise RuntimeError("manifest component_count does not match its component list")
    bundle_ids = [item.get("bundle_id") for item in components]
    if None in bundle_ids or len(set(bundle_ids)) != len(bundle_ids):
        raise RuntimeError("manifest has missing or repeated bundle IDs")
    for name in (manifest.get("components_file"), manifest.get("selection_file")):
        if not name or not (destination / name).is_file():
            raise RuntimeError(f"library file is missing: {name}")
    lock_path = destination / "library_lock.json"
    if not lock_path.is_file():
        raise RuntimeError("library_lock.json is missing")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("publication", {}).get("status") != "published":
        raise RuntimeError("library lock does not say published")

    corpus = None
    examples = {}
    if history_root is not None:
        corpus = load_corpus(history_root)
        examples = {example.task_id: example for example in corpus.examples}
    held_out = _held_out(corpus)

    findings: list[str] = []
    example_component: dict[str, str] = {}
    for record in components:
        bundle_id = record["bundle_id"]
        readme = destination / record["readme"]
        metadata_path = destination / record["metadata"]
        if not readme.is_file() or not metadata_path.is_file():
            findings.append(f"{bundle_id}: README or component.json is missing")
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("bundle_id") != bundle_id:
            findings.append(f"{bundle_id}: component.json bundle_id mismatch")
        if metadata.get("kind") != "transformation":
            findings.append(f"{bundle_id}: component.json is not a transformation")
        for project in (metadata.get("provenance") or {}).get("projects") or []:
            if project.lower() in held_out:
                findings.append(f"{bundle_id}: held-out project in provenance: {project}")
        task_ids = (metadata.get("provenance") or {}).get("task_ids") or []
        for task_id in task_ids:
            prior = example_component.get(task_id)
            if prior is not None and prior != bundle_id:
                findings.append(
                    f"{bundle_id}: example {task_id} already yielded {prior}; "
                    "one example yields exactly one component"
                )
            example_component.setdefault(task_id, bundle_id)
        example = next((examples[task] for task in task_ids if task in examples), None)
        findings.extend(
            f"{bundle_id}: {item}"
            for item in leakage_findings(
                metadata, example=example.metadata if example else None
            )
        )
    if findings:
        raise RuntimeError("library verification failed: " + "; ".join(findings[:10]))
    return {
        "schema": "methodology-library-verify-v1",
        "library": str(destination),
        "component_count": len(components),
        "history_digest": lock.get("history_digest"),
        "bundle_ids": bundle_ids,
        "status": "ok",
    }