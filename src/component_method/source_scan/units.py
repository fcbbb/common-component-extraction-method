"""Code-unit extraction from Python sources.

Top-level functions/classes remain units, and class methods are also exposed as
``method:Class.method`` units.  Method-level units matter for normal adapter
code: two backend classes can share a small compatibility method without being
near-duplicate classes.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

CONTAINER_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass
class Unit:
    unit_id: str
    kind: str  # "module" | "function" | "class" | "method"
    start: int  # 1-based inclusive
    end: int  # 1-based inclusive


def parse_units(source: str) -> tuple[Any | None, list[Unit], str | None]:
    """Return (tree, top-level units, error).

    The module unit spans rows not covered by any top-level function/class.
    A container for a given row is the unit with the smallest span containing it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return None, [], f"SyntaxError: {exc.msg} at line {exc.lineno}"
    units: list[Unit] = []
    body_span: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, CONTAINER_TYPES):
            kind = "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class"
            units.append(Unit(unit_id=f"{kind}:{node.name}", kind=kind, start=node.lineno, end=node.end_lineno or node.lineno))
            body_span.append((node.lineno, node.end_lineno or node.lineno))
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        units.append(
                            Unit(
                                unit_id=f"method:{node.name}.{child.name}",
                                kind="method",
                                start=child.lineno,
                                end=child.end_lineno or child.lineno,
                            )
                        )
    # module span: complement rows are handled by container_of_row; module unit only
    # needs to exist for lookup fallback, its span is the whole file.
    last_line = source.count("\n") + 1
    units.insert(0, Unit(unit_id="module", kind="module", start=1, end=last_line))
    return tree, units, None




def source_unit_records(source: str) -> list[dict[str, Any]]:
    """Extract source units without duplicating a class body into its module."""
    tree, _, error = parse_units(source)
    lines = source.splitlines(keepends=True)
    if tree is None or error:
        if source.strip():
            return [{"unit_id": "module", "kind": "module", "start": 1,
                     "end": max(1, len(lines)), "source_code": source}]
        return []

    records: list[dict[str, Any]] = []
    covered: list[tuple[int, int]] = []

    def add_node(unit_id: str, kind: str, node: ast.AST) -> None:
        start = getattr(node, "lineno", 1)
        decorator_rows = [d.lineno for d in getattr(node, "decorator_list", [])]
        if decorator_rows:
            start = min(start, *decorator_rows)
        end = getattr(node, "end_lineno", None) or start
        records.append({"unit_id": unit_id, "kind": kind, "start": start,
                        "end": end, "source_code": "".join(lines[start - 1:end])})

    for node in tree.body:
        if not isinstance(node, CONTAINER_TYPES):
            continue
        kind = "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class"
        add_node(f"{kind}:{node.name}", kind, node)
        start = getattr(node, "lineno", 1)
        decorator_rows = [d.lineno for d in getattr(node, "decorator_list", [])]
        if decorator_rows:
            start = min(start, *decorator_rows)
        covered.append((start, getattr(node, "end_lineno", None) or start))
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_node(f"method:{node.name}.{child.name}", "method", child)

    module_text = "".join(
        line if not any(start <= number <= end for start, end in covered) else "\n"
        for number, line in enumerate(lines, 1)
    )
    if module_text.strip():
        records.insert(0, {"unit_id": "module", "kind": "module", "start": 1,
                           "end": max(1, len(lines)), "source_code": module_text})
    return records


def module_is_trivial(source: str) -> bool:
    """Return true when the residual module body contains imports/constants only."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    def literal(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return all(literal(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return all(key is not None and literal(key) and literal(value)
                       for key, value in zip(node.keys, node.values))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            return literal(node.operand)
        return False

    if not tree.body:
        return False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Assign) and literal(node.value):
            continue
        if isinstance(node, ast.AnnAssign) and (node.value is None or literal(node.value)):
            continue
        return False
    return True


def class_method_context(source: str, method_unit_ids: set[str]) -> list[dict[str, Any]]:
    """Summarize owning-class state and calls for the candidate's methods."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    requested: dict[str, set[str]] = {}
    for unit_id in method_unit_ids:
        if not unit_id.startswith("method:"):
            continue
        class_name, separator, method_name = unit_id.split(":", 1)[1].partition(".")
        if separator:
            requested.setdefault(class_name, set()).add(method_name)

    contexts: list[dict[str, Any]] = []
    for class_node in tree.body:
        if not isinstance(class_node, ast.ClassDef) or class_node.name not in requested:
            continue
        class_methods = {
            child.name: child for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        matched = sorted(requested[class_node.name] & set(class_methods))
        if not matched:
            continue

        assigned_state: set[str] = set()
        class_state: set[str] = set()
        for child in class_node.body:
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        class_state.add(target.id)
                    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in {"self", "cls"}:
                        class_state.add(target.attr)

        access_by_method: dict[str, set[str]] = {}
        calls: set[tuple[str, str]] = set()
        for method_name, method_node in class_methods.items():
            accesses: set[str] = set()
            for node in ast.walk(method_node):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}:
                    accesses.add(node.attr)
                    if isinstance(node.ctx, ast.Store):
                        assigned_state.add(node.attr)
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in {"self", "cls"}
                    and node.func.attr in class_methods):
                    calls.add((method_name, node.func.attr))
            access_by_method[method_name] = accesses

        shared_state: set[str] = set()
        for index, first in enumerate(matched):
            for second in matched[index + 1:]:
                shared_state.update(
                    (access_by_method.get(first, set()) & access_by_method.get(second, set()))
                    & (assigned_state | class_state)
                )
        matched_calls = sorted((first, second) for first, second in calls
                               if first in matched and second in matched)
        relevant_state = set().union(*(
            access_by_method.get(name, set()) & (class_state | assigned_state)
            for name in matched
        ))
        contexts.append({
            "class_name": class_node.name,
            "bases": [ast.unparse(base) for base in class_node.bases],
            "matched_methods": matched,
            "class_state": sorted(relevant_state),
            "method_state_access": {
                name: sorted(access_by_method.get(name, set()) & (class_state | assigned_state))
                for name in matched
            },
            "shared_state": sorted(shared_state),
            "method_calls": [{"caller": first, "callee": second}
                             for first, second in sorted(calls) if first in matched],
            "matched_method_calls": [{"caller": first, "callee": second}
                                     for first, second in matched_calls],
            "related_methods": len(matched) > 1 and bool(shared_state or matched_calls),
        })
    return contexts
def container_of_row(units: list[Unit], row: int) -> Unit:
    """Deepest (smallest-span) unit containing the row; module is the fallback."""
    best: Unit = units[0]
    for unit in units:
        if unit.start <= row <= unit.end:
            if unit != best and (unit.end - unit.start) < (best.end - best.start):
                best = unit
    return best


def top_level_containers(tree: Any) -> list[ast.AST]:
    """Body statements of the module that are themselves container definitions."""
    return [node for node in tree.body if isinstance(node, CONTAINER_TYPES)]


def method_containers(tree: Any) -> list[tuple[str, ast.AST]]:
    """Return direct class methods with stable qualified unit names."""
    methods: list[tuple[str, ast.AST]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append((f"method:{node.name}.{child.name}", child))
    return methods


def module_body(tree: Any) -> list[ast.AST]:
    """Top-level statements that belong to the module unit (not nested in containers)."""
    return [node for node in tree.body if not isinstance(node, CONTAINER_TYPES)]


def unit_is_ancestor(parent_id: str, child_id: str) -> bool:
    """Return whether one stable unit id contains another unit id.

    Class spans contain their direct methods and can be used to normalize
    legacy class scopes. Module units are residual source, so they are siblings
    of top-level definitions rather than ancestors of the whole file.
    """
    if parent_id == child_id:
        return False
    if parent_id.startswith("class:") and child_id.startswith("method:"):
        class_name = parent_id.split(":", 1)[1]
        return child_id.startswith(f"method:{class_name}.")
    return False


def unit_is_ancestor_or_equal(first_id: str, second_id: str) -> bool:
    return first_id == second_id or unit_is_ancestor(first_id, second_id)
