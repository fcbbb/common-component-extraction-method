"Historical Python repair constraints."
from __future__ import annotations
import ast
import difflib
from typing import Any

def _validate_artifact_repair(
    content: str,
    component: dict[str, Any],
    *,
    max_changed_lines: int,
) -> None:
    tree = ast.parse(content)
    relative = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level]
    if relative:
        raise ValueError("repaired standalone artifact still contains relative imports")
    declared = {
        entry.get("name")
        for entry in component.get("entrypoints", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    if not declared <= defined:
        raise ValueError("repaired artifact removed a declared entrypoint")
    original = component.get("library", {}).get("content", "")
    changed = sum(
        1
        for line in difflib.ndiff(original.splitlines(), content.splitlines())
        if line.startswith(("- ", "+ "))
    )
    if changed > max_changed_lines:
        raise ValueError(f"artifact repair changed {changed} lines, above limit {max_changed_lines}")
