"""Materialize a validated task selection as a compact component bundle."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from .submission import validate_selection


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _inline(value: Any) -> str:
    text = " ".join(str(value or "").split())
    for character in "\\`*_{}[]<>|":
        text = text.replace(character, "\\" + character)
    return text


def _change_model_lines(selection: dict[str, Any]) -> list[str]:
    change_model = selection.get("change_model")
    if not isinstance(change_model, dict):
        return []
    lines = [
        "## Change propagation",
        "",
        "The retrieval Agent identified these repository-wide obligations before selecting "
        "components. Check them as a closure list, including sibling operations not named in "
        "the task.",
        "",
        "### Required closure check",
        "",
        "Before editing, turn every introduced variant into its role-independent carrier "
        "(for example a value, type object, sentinel, format, or state). Build a matrix of that "
        "carrier against every sibling operation in the selected source that accepts the same "
        "semantic kind, and against every applicable argument position. A variant named in one "
        "task method is not limited to that method. Add focused assertions under `/tmp` for each "
        "applicable matrix row and do not submit while any row is untested or inconsistent.",
        "",
        "Before the final submission, inspect the Git diff and remove scratch or probe files from "
        "the repository; only intended production changes may remain.",
        "",
    ]
    sections = (
        ("Changed entities", "changed_entities"),
        ("Introduced or changed variants", "introduced_or_changed_variants"),
        ("Propagation risks", "propagation_risks"),
    )
    for title, key in sections:
        values = change_model.get(key)
        if isinstance(values, list) and values:
            lines.append(f"### {title}")
            lines.append("")
            lines.extend(f"- {_inline(value)}" for value in values)
            lines.append("")
    return lines


def _propagation_check_lines(selection: dict[str, Any]) -> list[str]:
    checks = selection.get("propagation_checks")
    if not isinstance(checks, list) or not checks:
        return []
    lines = ["## Propagation check matrix", ""]
    for index, check in enumerate(checks, start=1):
        lines.extend([
            f"### Check {index}: {_inline(check['carrier'])}",
            "",
            "- Variants: " + "; ".join(_inline(value) for value in check["changed_variants"]),
            "- Components: " + ", ".join(f"`{_inline(value)}`" for value in check["bundle_ids"]),
            "- Symbols: " + "; ".join(_inline(value) for value in check["symbols"]),
            "- Argument positions: "
            + "; ".join(_inline(value) for value in check["argument_positions"]),
            "- Required invariant: " + _inline(check["invariant"]),
            "- Required validation: add a focused `/tmp` assertion for every applicable "
            "symbol and argument-position row before submission.",
            "",
        ])
    return lines


def _index_entry(
    bundle_id: str,
    record: dict[str, Any],
    audit: dict[str, Any],
    selected: dict[str, Any],
) -> list[str]:
    name = _inline(audit.get("name") or bundle_id)
    capability = _inline(
        audit.get("capability") or audit.get("summary") or "See the component documentation."
    )
    if len(capability) > 240:
        capability = capability[:239].rstrip() + "…"
    return [
        f"## [{name}]({record['readme']})",
        "",
        f"- Library capability: {capability}",
        f"- Delivery mode: `{selected['delivery_mode']}`",
        f"- Task overlap: {_inline(selected['task_overlap'])}",
        f"- Incremental contribution: {_inline(selected['incremental_contribution'])}",
        f"- How to use: {_inline(selected['usage'])}",
        f"- Boundary: {_inline(selected['boundary'])}",
        f"- Stable import: `{record['import_module']}`",
        f"- Files: `components/{bundle_id}/`",
        "",
    ]


def _selection_markdown(selection: dict[str, Any]) -> str:
    lines = [
        "# Component selection evidence",
        "",
        "These components were selected for reusable work or repository knowledge not already "
        "present in the task statement. They are not patch instructions.",
        "",
        "## Task baseline",
        "",
    ]
    for fact in selection["task_baseline"]["explicit_information"]:
        lines.append(f"- {_inline(fact)}")
    lines.extend(
        [
            "",
            f"Obvious implementation scope: {_inline(selection['task_baseline']['obvious_scope'])}",
            "",
        ]
    )
    lines.extend(_change_model_lines(selection))
    lines.extend(_propagation_check_lines(selection))
    for selected in selection["selected"]:
        lines.extend(
            [
                f"## {selected['bundle_id']}",
                "",
                f"- Delivery mode: `{selected['delivery_mode']}`",
                f"- Task overlap: {_inline(selected['task_overlap'])}",
                "- Incremental contribution: "
                + _inline(selected["incremental_contribution"]),
                f"- How to use: {_inline(selected['usage'])}",
                f"- Boundary: {_inline(selected['boundary'])}",
                "- Frozen-library evidence:",
            ]
        )
        for evidence in selected["evidence"]:
            location = (
                f"{evidence['path']}:{evidence['line_start']}"
                if evidence["line_start"] == evidence["line_end"]
                else f"{evidence['path']}:{evidence['line_start']}-{evidence['line_end']}"
            )
            lines.append(f"  - `{_inline(location)}`: {_inline(evidence['excerpt'])}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _entrypoint_names(audit: dict[str, Any]) -> list[str]:
    names = []
    for entry in audit.get("entrypoints", []):
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.isidentifier() and name not in names:
            names.append(name)
    return names


def _document_stable_import(
    readme: Path,
    *,
    import_module: str,
    entrypoints: list[str],
    selected: dict[str, Any],
) -> None:
    names = ", ".join(entrypoints) if entrypoints else "the documented entrypoint"
    note = (
        "## Task retrieval note\n\n"
        "This component was selected because it contributes reusable work or repository "
        "knowledge beyond the task statement.\n\n"
        f"Delivery mode: `{selected['delivery_mode']}`.\n\n"
        f"Task overlap: {_inline(selected['task_overlap'])}\n\n"
        "Incremental contribution: "
        f"{_inline(selected['incremental_contribution'])}\n\n"
        f"How to use: {_inline(selected['usage'])}\n\n"
        f"Boundary: {_inline(selected['boundary'])}\n\n"
        "## Stable task import\n\n"
        f"Import {names} from `{import_module}`. The selected bundle root is on "
        "`PYTHONPATH` during task execution and evaluation.\n\n"
    )
    content = readme.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    insertion = 1 if lines and lines[0].startswith("# ") else 0
    lines[insertion:insertion] = ["\n", note]
    readme.write_text("".join(lines), encoding="utf-8")


def materialize_selected_bundle(
    source_library: Path,
    selection_path: Path,
    destination: Path,
    *,
    expected_task_id: str | None = None,
) -> Path:
    """Copy the validated selected entries into a new read-only bundle.

    Selection relevance is decided upstream by the retrieval agent. This function
    only validates that decision and performs a mechanical, identity-preserving
    subset operation over an already published bundle.
    """
    source_library = source_library.expanduser().resolve()
    destination = destination.expanduser().resolve()
    selection = validate_selection(
        source_library,
        selection_path,
        expected_task_id=expected_task_id,
    )
    source_manifest = json.loads(
        (source_library / "manifest.json").read_text(encoding="utf-8")
    )
    if source_manifest.get("schema_version") == 8:
        from component_method.library_publish.artifacts import select_artifact_bundle

        return select_artifact_bundle(source_library, selection, destination)
    records_by_id = {
        record["bundle_id"]: record for record in source_manifest["components"]
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"selected component bundle already exists: {destination}")
    staging = Path(tempfile.mkdtemp(prefix=".selection-bundle-", dir=destination.parent))
    # The task container has no DAC override after dropping all capabilities.
    # The bind-mount root must therefore be traversable, not only its children.
    staging.chmod(0o755)
    try:
        records: list[dict[str, Any]] = []
        libraries: list[str] = []
        selected_by_id = {
            item["bundle_id"]: item for item in selection["selected"]
        }
        index_lines = [
            "# Component index",
            "",
            f"{len(selection['selected_bundle_ids'])} components selected for this task. "
            "Each entry contributes reusable work or repository knowledge beyond the task "
            "statement. Full source citations are in "
            "[SELECTION.md](SELECTION.md).",
            "",
            "- `direct_reuse`: call an existing documented operation for a task suboperation.",
            "- `reference_pattern`: study and adapt a concrete repository pattern or protocol.",
            "",
        ]
        index_lines.extend(_change_model_lines(selection))
        index_lines.extend(_propagation_check_lines(selection))
        api_dir = staging / "component_api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text(
            '"""Stable imports for the components selected for this task."""\n',
            encoding="utf-8",
        )
        for bundle_id in selection["selected_bundle_ids"]:
            selected = selected_by_id[bundle_id]
            source_record = records_by_id[bundle_id]
            import_module = f"component_api.{bundle_id.replace('-', '_')}"
            record = {
                key: source_record[key]
                for key in ("bundle_id", "library", "readme", "audit_file")
            }
            record["import_module"] = import_module
            for field in ("library", "readme", "audit_file"):
                relative = Path(record[field])
                source = (source_library / relative).resolve()
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"unsafe selected component path: {relative}")
                try:
                    source.relative_to(source_library)
                except ValueError as exc:
                    raise ValueError(f"selected component path escapes bundle: {relative}") from exc
                if not source.is_file():
                    raise FileNotFoundError(f"selected component file is missing: {relative}")
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            audit = json.loads((staging / record["audit_file"]).read_text(encoding="utf-8"))
            shutil.copyfile(
                staging / record["library"],
                api_dir / f"{bundle_id.replace('-', '_')}.py",
            )
            _document_stable_import(
                staging / record["readme"],
                import_module=import_module,
                entrypoints=_entrypoint_names(audit),
                selected=selected,
            )
            records.append(record)
            libraries.append(record["library"])
            index_lines.extend(_index_entry(bundle_id, record, audit, selected))

        (staging / "INDEX.md").write_text(
            "\n".join(index_lines) + "\n",
            encoding="utf-8",
        )
        _write_json(staging / "selection.json", selection)
        (staging / "SELECTION.md").write_text(
            _selection_markdown(selection),
            encoding="utf-8",
        )
        source_readme = source_library / "README.md"
        if source_readme.is_file():
            shutil.copyfile(source_readme, staging / "README.md")
        else:
            (staging / "README.md").write_text(
                "# Component bundle\n\nRead [INDEX.md](INDEX.md) for the selected components.\n",
                encoding="utf-8",
            )

        manifest = dict(source_manifest)
        manifest.update(
            generated_at=datetime.now(timezone.utc).isoformat(),
            component_count=len(records),
            components_file="INDEX.md",
            libraries=libraries,
            components=records,
            selection_method="validated_task_retrieval_subset",
            selection_file="selection.json",
            selection_document="SELECTION.md",
            selected_bundle_ids=selection["selected_bundle_ids"],
            stable_import_package="component_api",
        )
        _write_json(staging / "manifest.json", manifest)
        for path in staging.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        os.replace(staging, destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)
