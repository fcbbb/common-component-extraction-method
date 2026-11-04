"""Generate and validate task-blind guidance for mined component candidates."""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import re
import symtable
import sys
from pathlib import Path
from typing import Any

from .json_utils import extract_json_object, require_library_schema
from .llm_client import DeepSeekClient
from .support import PROMPT_DIR, build_user_prompt, read_text, save_call_log, write_json
from component_method.source_scan.units import source_unit_records

CONTEXT_SYSTEM = PROMPT_DIR / "component_context_system.txt"
CONTEXT_USER = PROMPT_DIR / "component_context_user_template.txt"
CONTEXT_GATE_SYSTEM = PROMPT_DIR / "component_review_system.txt"
CONTEXT_GATE_USER = PROMPT_DIR / "component_review_user_template.txt"
MAX_CONTEXT_EXTRACTION_ATTEMPTS = 3
MAX_PREVIOUS_RESPONSE_CHARS = 12000


def _prompt_meta() -> dict[str, str]:
    return {
        "gate_system": hashlib.sha256(CONTEXT_GATE_SYSTEM.read_bytes()).hexdigest(),
        "gate_user": hashlib.sha256(CONTEXT_GATE_USER.read_bytes()).hexdigest(),
        "common_system": hashlib.sha256(CONTEXT_SYSTEM.read_bytes()).hexdigest(),
        "common_user": hashlib.sha256(CONTEXT_USER.read_bytes()).hexdigest(),
    }


def _validate_context_common(payload: dict[str, Any]) -> None:
    if payload.get("status") != "draft_ready":
        raise ValueError("component context must return status='draft_ready'")
    require_library_schema(payload)
    guidance = payload.get("agent_guidance")
    if not isinstance(guidance, dict):
        raise ValueError("component context must include agent_guidance")
    if not isinstance(guidance.get("summary"), str):
        raise ValueError("agent_guidance.summary must be a string")
    for field in ("invariants", "variation_points", "pitfalls", "recommended_use"):
        values = guidance.get(field)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError(f"agent_guidance.{field} must be a list of strings")


def _call_context_common(
    client: DeepSeekClient,
    cluster: dict[str, Any],
    dataset_dir: Path,
    out_dir: Path,
    subcluster: dict[str, Any],
    *,
    attempt: int = 1,
    validation_feedback: str | None = None,
    previous_response: str | None = None,
) -> dict[str, Any]:
    members = set(subcluster["members"])
    payload = {
        "cluster_id": cluster["cluster_id"],
        "subcluster": subcluster,
        "files": [
            {
                "file_id": item["file_id"],
                "rel_path": item["rel_path"],
                "source_code": (
                    dataset_dir / "clusters" / cluster["cluster_id"] / "original" / item["file_id"]
                ).read_text(encoding="utf-8"),
            }
            for item in cluster["files"]
            if item["file_id"] in members
        ],
    }
    system_prompt = read_text(CONTEXT_SYSTEM)
    user_prompt = build_user_prompt(CONTEXT_USER, payload)
    if validation_feedback:
        user_prompt += (
            "\n\nYour previous draft did not pass private local validation. "
            "You cannot inspect or invoke that validator. Revise the complete artifact "
            "using only this feedback, then return a new draft. Do not claim it passed.\n"
            "Validation feedback:\n"
            + validation_feedback
        )
    if previous_response:
        user_prompt += (
            "\n\nPrevious draft to revise:\n"
            + previous_response[:MAX_PREVIOUS_RESPONSE_CHARS]
        )
    prompt_paths = {"system": str(CONTEXT_SYSTEM), "user_template": str(CONTEXT_USER)}
    response = client.chat(system_prompt, user_prompt)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if attempt == 1 else f".retry{attempt - 1}"
    (out_dir / f"component_context_raw_response{suffix}.txt").write_text(
        response.content, encoding="utf-8"
    )
    write_json(out_dir / f"component_context_raw_api_response{suffix}.json", response.raw)
    save_call_log(
        out_dir / f"component_context_call_log{suffix}.json",
        response,
        "component_context",
        subcluster["cluster_id"],
        prompt_paths,
    )
    result = extract_json_object(response.content)
    _validate_context_common(result)
    return result


def _validation_feedback(validation: dict[str, Any]) -> str:
    fields = (
        "status",
        "reason",
        "compile",
        "invented_imports",
        "undefined_names",
    )
    summary = {field: validation[field] for field in fields if field in validation}
    return json.dumps(summary, ensure_ascii=False, indent=2)


def run_context_extraction_loop(
    client: DeepSeekClient,
    cluster: dict[str, Any],
    dataset_dir: Path,
    out_dir: Path,
    subcluster: dict[str, Any],
    source_by_id: dict[str, str],
    *,
    max_attempts: int = MAX_CONTEXT_EXTRACTION_ATTEMPTS,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Generate, locally validate, and repair one accepted component pattern."""
    max_attempts = max(1, int(max_attempts))
    attempts: list[dict[str, Any]] = []
    feedback: str | None = None
    previous_response: str | None = None
    last_validation: dict[str, Any] = {}

    for attempt in range(1, max_attempts + 1):
        attempt_dir = out_dir / "attempts" / f"attempt_{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] | None = None
        try:
            payload = _call_context_common(
                client,
                cluster,
                dataset_dir,
                attempt_dir,
                subcluster,
                attempt=attempt,
                validation_feedback=feedback,
                previous_response=previous_response,
            )
            validation = _validate_common_reference(
                payload,
                subcluster,
                source_by_id,
                attempt_dir,
            )
        except Exception as exc:  # Each failed draft becomes feedback for the next attempt.
            validation = {
                "subcluster_id": subcluster["cluster_id"],
                "status": "generation_failed",
                "reason": repr(exc),
            }

        write_json(attempt_dir / "validation.json", validation)
        last_validation = validation
        attempt_record = {
            "attempt": attempt,
            "status": validation.get("status"),
        }
        for field in ("reason", "compile", "invented_imports", "undefined_names"):
            if field in validation:
                attempt_record[field] = validation[field]
        attempts.append(attempt_record)

        if validation.get("status") == "ok" and payload is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "common.py").write_text(
                payload["library"]["content"],
                encoding="utf-8",
            )
            final_validation = {
                **validation,
                "attempt_count": attempt,
                "attempts": attempts,
            }
            write_json(out_dir / "validation.json", final_validation)
            return payload, final_validation

        feedback = _validation_feedback(validation)
        if payload is not None:
            previous_response = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            suffix = "" if attempt == 1 else f".retry{attempt - 1}"
            raw_path = attempt_dir / f"component_context_raw_response{suffix}.txt"
            previous_response = (
                raw_path.read_text(encoding="utf-8")[:MAX_PREVIOUS_RESPONSE_CHARS]
                if raw_path.is_file()
                else None
            )

    if last_validation.get("status") in {"compile_failed", "empty", "ungrounded"}:
        final_validation = {
            **last_validation,
            "status": "repair_exhausted",
            "reason": (
                f"Local validation still failed after {max_attempts} extraction attempts: "
                f"{last_validation.get('reason', last_validation.get('status'))}"
            ),
            "attempt_count": max_attempts,
            "attempts": attempts,
        }
    else:
        final_validation = {
            "subcluster_id": subcluster["cluster_id"],
            "status": "generation_failed",
            "reason": f"No valid extraction draft after {max_attempts} attempts",
            "attempt_count": max_attempts,
            "attempts": attempts,
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "validation.json", final_validation)
    return None, final_validation


def _member_evidence(source: str) -> tuple[set[str], set[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set(), set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source))
    modules: set[str] = set()
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                identifiers.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                modules.add(node.module)
            identifiers.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
    return modules, identifiers


def _stdlib_module_roots() -> frozenset[str]:
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return frozenset(names)
    return frozenset({
        "abc", "collections", "dataclasses", "enum", "functools", "itertools",
        "math", "operator", "os", "re", "sys", "time", "types", "typing", "warnings",
    })


_STDLIB_MODULE_ROOTS = _stdlib_module_roots()


def _undefined_names(source: str, grounded_names: set[str]) -> list[str]:
    scopes = symtable.symtable(source, "common.py", "exec")
    module_names = {
        symbol.get_name()
        for symbol in scopes.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    known_names = module_names | grounded_names | set(vars(builtins))
    referenced_globals: set[str] = set()

    def collect(scope: symtable.SymbolTable) -> None:
        for symbol in scope.get_symbols():
            if symbol.is_global() and symbol.is_referenced():
                referenced_globals.add(symbol.get_name())
        for child in scope.get_children():
            collect(child)

    collect(scopes)
    return sorted(referenced_globals - known_names)


def _validate_common_reference(
    common_payload: dict[str, Any],
    subcluster: dict[str, Any],
    source_by_id: dict[str, str],
    out_dir: Path,
    *,
    allow_repository_imports: bool = False,
) -> dict[str, Any]:
    content = common_payload["library"]["content"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "common.py").write_text(content, encoding="utf-8")
    try:
        compile(content, str(out_dir / "common.py"), "exec")
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        compile_info = {"ok": False, "error": str(exc)}
        return {
            "subcluster_id": subcluster["cluster_id"],
            "status": "compile_failed",
            "reason": "common.py does not compile",
            "compile": compile_info,
        }
    compile_info = {"ok": True}
    defined: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.append(node.name)
        elif isinstance(node, ast.Assign):
            defined.extend(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.append(node.target.id)
    if not defined:
        return {
            "subcluster_id": subcluster["cluster_id"],
            "status": "empty",
            "reason": "common.py defines no top-level API",
            "compile": compile_info,
            "defined_names": defined,
        }

    member_modules: set[str] = set()
    member_identifiers: set[str] = set()
    for file_id in subcluster["members"]:
        modules, identifiers = _member_evidence(source_by_id[file_id])
        member_modules.update(modules)
        member_identifiers.update(identifiers)

    imported_modules: list[str] = []
    imported_names: list[str] = []
    stdlib_imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            if node.module and node.level == 0:
                imported_modules.append(node.module)
                if node.module.split(".")[0] in _STDLIB_MODULE_ROOTS:
                    stdlib_imported_names.update(alias.name for alias in node.names)
            imported_names.extend(alias.name for alias in node.names)
    repository_imports = []
    if allow_repository_imports:
        for module in set(imported_modules):
            stem = module.replace(".", "/")
            # Repository imports can use either the flat or the src/ layout.
            # Keep the original source path as evidence in both cases.
            paths = [prefix + suffix for prefix in ("", "src/")
                     for suffix in (stem + ".py", stem + "/__init__.py")]
            file_id = next((path for path in paths
                            if path in source_by_id), None)
            if file_id is not None:
                member_modules.add(module)
                _, identifiers = _member_evidence(source_by_id[file_id])
                member_identifiers.update(identifiers)
                repository_imports.append(file_id)
    invented_modules = sorted(
        module for module in set(imported_modules) - member_modules
        if module.split(".")[0] not in _STDLIB_MODULE_ROOTS
    )
    invented_import_names = sorted(set(imported_names) - member_identifiers - stdlib_imported_names)
    undefined_names = _undefined_names(content, member_identifiers)
    if invented_modules or invented_import_names or undefined_names:
        details = []
        if invented_modules:
            details.append("modules not present in member sources: " + ", ".join(invented_modules))
        if invented_import_names:
            details.append("imported names not present in member sources: " + ", ".join(invented_import_names))
        if undefined_names:
            details.append("undefined names: " + ", ".join(undefined_names))
        return {
            "subcluster_id": subcluster["cluster_id"],
            "status": "ungrounded",
            "reason": "; ".join(details),
            "compile": compile_info,
            "defined_names": defined,
            "invented_imports": invented_modules + invented_import_names,
            "undefined_names": undefined_names,
        }
    return {
        "subcluster_id": subcluster["cluster_id"],
        "status": "ok",
        "compile": compile_info,
        "defined_names": defined,
        "repository_imports": sorted(repository_imports),
    }


def _load_source_units(source: str, unit_ids: list[str]) -> list[dict[str, Any]]:
    records = source_unit_records(source)
    by_id = {record["unit_id"]: record for record in records}
    selected = []
    for unit_id in unit_ids or ["module"]:
        record = by_id.get(unit_id)
        if record is not None:
            selected.append({
                "unit_id": unit_id,
                "start": record["start"],
                "end": record["end"],
                "content": record["source_code"],
            })
    if selected:
        return selected
    return [{
        "unit_id": "module",
        "start": 1,
        "end": max(1, len(source.splitlines())),
        "content": source,
    }]


def _write_snippets(
    context_root: Path,
    subcluster: dict[str, Any],
    file_by_id: dict[str, dict[str, Any]],
    source_by_id: dict[str, str],
) -> Path:
    path = context_root / "snippets" / f"{subcluster['cluster_id']}.md"
    lines = [f"# Source evidence: {subcluster['cluster_id']}", ""]
    for file_id in subcluster["members"]:
        entry = file_by_id[file_id]
        lines.extend([f"## `{entry['rel_path']}`", ""])
        unit_ids = subcluster.get("units", {}).get(file_id, [])
        for unit in _load_source_units(source_by_id[file_id], unit_ids):
            lines.extend([
                f"### `{unit['unit_id']}` (lines {unit['start']}-{unit['end']})",
                "",
                "```python",
                unit["content"].rstrip("\n"),
                "```",
                "",
            ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
