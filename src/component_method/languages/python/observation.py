"Python expression and frame coverage checks for v1 compatibility."
from __future__ import annotations
import ast
from typing import Any

def _smoke_call_constants(run: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[int, dict[str, Any]]:
    """Track immutable scalar bindings in statement order; leave complex flow unknown."""
    unknown = object()

    class Calls(ast.NodeVisitor):
        def __init__(self):
            self.bindings = {}
            self.calls = {}
            self.enabled = not any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(run))

        def value(self, node):
            if isinstance(node, ast.Name):
                return self.bindings.get(node.id, unknown)
            try:
                result = ast.literal_eval(node)
            except (ValueError, TypeError, SyntaxError):
                return unknown
            return result if type(result) in (str, bytes, int, float, complex, bool, type(None)) else unknown

        def forget(self, target):
            for node in ast.walk(target):
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    self.bindings.pop(node.id, None)

        def visit_Assign(self, node):
            self.visit(node.value)
            value = self.value(node.value) if self.enabled else unknown
            for target in node.targets:
                self.forget(target)
                if isinstance(target, ast.Name) and value is not unknown:
                    self.bindings[target.id] = value

        def visit_AnnAssign(self, node):
            if node.value is None:
                return
            self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

        def visit_AugAssign(self, node):
            self.visit(node.value)
            self.forget(node.target)

        def visit_Delete(self, node):
            for target in node.targets:
                self.forget(target)

        def visit_NamedExpr(self, node):
            self.visit(node.value)
            self.forget(node.target)

        def visit_Call(self, node):
            dynamic_args = any(isinstance(child, ast.NamedExpr) for child in ast.walk(node))
            self.calls[id(node)] = dict(self.bindings) if self.enabled and not dynamic_args else {}
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval", "locals", "globals"}:
                self.bindings.clear()

        def visit_FunctionDef(self, node):
            self.bindings.pop(node.name, None)

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def visit_Lambda(self, node):
            pass

        def visit_compound(self, node):
            enabled = self.enabled
            self.enabled = False
            self.bindings.clear()
            self.generic_visit(node)
            self.bindings.clear()
            self.enabled = enabled

        visit_If = visit_compound
        visit_For = visit_compound
        visit_AsyncFor = visit_compound
        visit_While = visit_compound
        visit_Try = visit_compound
        visit_TryStar = visit_compound
        visit_With = visit_compound
        visit_AsyncWith = visit_compound
        visit_Match = visit_compound
        visit_ListComp = visit_compound
        visit_SetComp = visit_compound
        visit_DictComp = visit_compound
        visit_GeneratorExp = visit_compound

    visitor = Calls()
    for statement in run.body:
        visitor.visit(statement)
    return visitor.calls


def _case_exercises_path(source: str, entrypoint: str, path: str) -> bool:
    """Require the named method or concrete input mode, beyond constructing its class."""
    try:
        expected = ast.parse(path, mode="eval").body
        run = next(node for node in ast.parse(source).body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run")
        parameter = run.args.args[0].arg
    except (SyntaxError, StopIteration, IndexError):
        return False
    expected_call = expected if isinstance(expected, ast.Call) else None
    target = expected.func if expected_call else expected
    target_parts = ast.unparse(target).split(".")
    if target_parts[0] != entrypoint or len(target_parts) > 2:
        return False
    aliases = {}
    instances = set()
    call_constants = _smoke_call_constants(run)

    def argument_matches(expected, actual, bindings):
        if isinstance(actual, ast.Name) and actual.id in bindings:
            actual = ast.Constant(value=bindings[actual.id])
        try:
            wanted, supplied = ast.literal_eval(expected), ast.literal_eval(actual)
            return type(wanted) is type(supplied) and wanted == supplied
        except (ValueError, TypeError, SyntaxError):
            return ast.dump(expected) == ast.dump(actual)

    def is_entry(node):
        return ((isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                 and node.value.id == parameter and node.attr == entrypoint)
                or (isinstance(node, ast.Name) and aliases.get(node.id) == entrypoint))

    # A concrete subclass is also a supported class entrypoint receiver.
    for node in ast.walk(run):
        if isinstance(node, ast.ClassDef) and any(is_entry(base) for base in node.bases):
            aliases[node.name] = entrypoint
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if is_entry(node.value):
                for name in targets:
                    if isinstance(name, ast.Name):
                        aliases[name.id] = entrypoint
            if isinstance(node.value, ast.Call) and is_entry(node.value.func):
                instances.update(name.id for name in targets if isinstance(name, ast.Name))
    for node in ast.walk(run):
        if not isinstance(node, ast.Call) or id(node) not in call_constants:
            continue
        matches = is_entry(node.func) if len(target_parts) == 1 else (
            isinstance(node.func, ast.Attribute) and node.func.attr == target_parts[1]
            and ((isinstance(node.func.value, ast.Name) and node.func.value.id in instances)
                 or is_entry(node.func.value)
                 or (isinstance(node.func.value, ast.Call) and is_entry(node.func.value.func)))
        )
        if not matches:
            continue
        if expected_call:
            bindings = call_constants[id(node)]
            actual_keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            if any(keyword.arg not in actual_keywords or not argument_matches(
                    keyword.value, actual_keywords[keyword.arg], bindings) for keyword in expected_call.keywords):
                continue
            if len(node.args) < len(expected_call.args) or any(not argument_matches(a, b, bindings)
                    for a, b in zip(expected_call.args, node.args)):
                continue
        return True
    return False


def _runtime_exercises_path(result: dict[str, Any], entrypoint: str, path: str) -> bool:
    """Credit only a matching original callable observed during this case's execution."""
    try:
        expected = ast.parse(path, mode="eval").body
        call = expected if isinstance(expected, ast.Call) else None
        target = ast.unparse(call.func if call else expected)
        parts = target.split(".")
        if parts[0] != entrypoint or len(parts) > 2:
            return False
    except (SyntaxError, ValueError):
        return False

    def matches(wanted, observed):
        if not isinstance(observed, dict):
            return False
        try:
            expected_value = ast.literal_eval(wanted)
            actual_value = ast.literal_eval(observed["literal"])
            return type(expected_value) is type(actual_value) and expected_value == actual_value
        except (ValueError, TypeError, SyntaxError, KeyError):
            return False

    for observed in result.get("execution_observations", []):
        if observed.get("entrypoint") != entrypoint or observed.get("path") != target:
            continue
        if call:
            arguments = observed.get("arguments", {})
            positional = observed.get("positional", [])
            if (any(keyword.arg not in arguments or not matches(keyword.value, arguments[keyword.arg])
                    for keyword in call.keywords)
                    or len(positional) < len(call.args)
                    or any(not matches(wanted, actual) for wanted, actual in zip(call.args, positional))):
                continue
        return True
    return False


def _unreported_class_paths(library_content, entrypoints, capabilities):
    """Make omitted class methods visible as unverified, rather than imply class-wide coverage."""
    declared = {entry["name"] for entry in entrypoints if entry.get("kind") == "class"}
    present = {cap["path"].split("(", 1)[0] for cap in capabilities}
    result = []
    try:
        tree = ast.parse(library_content)
    except SyntaxError:
        return []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in declared:
            continue
        for member in node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            path = f"{node.name}.{member.name}"
            if path in present or (member.name.startswith("__") and member.name != "__call__"):
                continue
            result.append({"entrypoint": node.name, "path": path, "availability": "unverified",
                           "validation_status": "unverified", "contract": "", "example": "", "scope": "Coverage not recorded",
                           "reason": "No capability case was declared for this method", "case_ids": []})
    return result


def _capability_path(cap: dict[str, Any], names: dict[str, Any]) -> str:
    """Derive machine coverage from the declared callable only."""
    entrypoint = cap.get("entrypoint")
    if not isinstance(entrypoint, str) or entrypoint not in names:
        raise ValueError("entrypoint is outside the extracted draft")
    if "method" not in cap:
        # Existing saved reviews retain their original expression-based contract.
        path = cap.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("capability has no path or structured callable declaration")
        return path
    method = cap.get("method", "")
    if not isinstance(method, str) or (method and not method.isidentifier()):
        raise ValueError("method must be empty or one Python identifier")
    if method and names[entrypoint].get("kind") != "class":
        raise ValueError("only class entrypoints may declare a method")
    return entrypoint + ("." + method if method else "")
