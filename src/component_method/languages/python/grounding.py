"Python source grounding for historical context extraction."
from __future__ import annotations
import ast
import builtins
import re
import symtable
import sys
from pathlib import Path
from typing import Any

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
