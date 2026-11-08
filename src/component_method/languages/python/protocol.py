"""Python protocol facts extracted with the standard AST parser."""
from __future__ import annotations
import ast
import textwrap
import warnings
from dataclasses import dataclass, field
from typing import Iterable
from .units import source_unit_records
from component_method.languages.contracts import UnitProfile as Profile, SourceUnit
Node = tuple[str, str]

COMMON_CALLS = {
    "append", "copy", "extend", "get", "items", "keys", "len", "list",
    "pop", "range", "set", "sorted", "str", "tuple", "type", "update",
    "values", "zip", "super", "getattr", "setattr", "hasattr", "print",
}
COMMON_NAMES = {
    "args", "kwargs", "value", "values", "result", "results", "self", "cls",
    "obj", "object", "item", "items", "data", "name", "type", "state", "key",
}
PROTOCOL_CALLS = {
    "get_origin", "get_args", "isinstance", "issubclass", "register",
    "register_serializer", "serialize", "deserialize", "dispatch", "visit",
}


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _tail(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _meaningful_name(name: str) -> bool:
    return (
        name not in COMMON_NAMES
        and len(name) >= 5
        and ("_" in name or name.startswith(("old", "previous", "cached", "original")))
    )


def _lifecycle_name(name: str) -> bool:
    return name.startswith(("old_", "previous_", "cached_", "original_", "deleted_"))


@dataclass
class UnitProfile:
    node: Node
    kind: str
    source_code: str
    owner_class: str | None = None
    defined_symbols: set[str] = field(default_factory=set)
    references: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    protocol_symbols: set[str] = field(default_factory=set)
    registration_keys: set[str] = field(default_factory=set)
    flow_names: set[str] = field(default_factory=set)
    self_fields: set[str] = field(default_factory=set)
    self_calls: set[str] = field(default_factory=set)


class _ProfileVisitor(ast.NodeVisitor):
    def __init__(self, profile: UnitProfile) -> None:
        self.profile = profile

    def visit_Name(self, node: ast.Name) -> None:
        self.profile.references.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = _qualified_name(node)
        if name:
            self.profile.references.update((name, _tail(name)))
        if isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}:
            self.profile.self_fields.add(node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _qualified_name(node.func)
        if name:
            tail = _tail(name)
            self.profile.calls.update((name, tail))
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id in {"self", "cls"}:
                    self.profile.self_calls.add(tail)
            if tail in PROTOCOL_CALLS:
                self.profile.protocol_symbols.add(f"call:{tail}")
                for arg in node.args[:3]:
                    symbol = _qualified_name(arg)
                    if symbol:
                        self.profile.protocol_symbols.update((symbol, _tail(symbol)))
            if tail.startswith("register") or tail in {"dispatch", "visit"}:
                args = [_qualified_name(arg) for arg in node.args[:2]]
                key = ":".join([name, *(arg for arg in args if arg)])
                self.profile.registration_keys.add(key)
        for keyword in node.keywords:
            if keyword.arg and _meaningful_name(keyword.arg):
                self.profile.flow_names.add(keyword.arg)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg:
            args.append(node.args.vararg)
        if node.args.kwarg:
            args.append(node.args.kwarg)
        self.profile.flow_names.update(arg.arg for arg in args if _meaningful_name(arg.arg))
        for decorator in node.decorator_list:
            name = _qualified_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            if name and (_tail(name).startswith("register") or _tail(name) in {"dispatch", "visit"}):
                self.profile.registration_keys.add(f"decorator:{name}")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and _meaningful_name(target.id):
                self.profile.flow_names.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and _meaningful_name(node.target.id):
            self.profile.flow_names.add(node.target.id)
        self.generic_visit(node)


def build_profiles(sources: Iterable[dict[str, str]]) -> dict[Node, UnitProfile]:
    profiles: dict[Node, UnitProfile] = {}
    for entry in sources:
        file_id = entry["file_id"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            records = source_unit_records(entry["source_code"])
        for record in records:
            unit_id = record["unit_id"]
            owner = None
            if unit_id.startswith("method:"):
                owner = unit_id.split(":", 1)[1].split(".", 1)[0]
            profile = UnitProfile(
                node=(file_id, unit_id),
                kind=record["kind"],
                source_code=record["source_code"],
                owner_class=owner,
            )
            if unit_id != "module":
                qualified = unit_id.split(":", 1)[1]
                profile.defined_symbols.update((qualified, qualified.rsplit(".", 1)[-1]))
                if owner:
                    profile.defined_symbols.add(owner)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(textwrap.dedent(record["source_code"]))
            except SyntaxError:
                profiles[profile.node] = profile
                continue
            _ProfileVisitor(profile).visit(tree)
            profiles[profile.node] = profile
    return profiles



def profile_unit(unit: SourceUnit) -> Profile:
    owner = unit.parent_qualified_name
    p = UnitProfile((unit.file_id, unit.metadata["legacy_unit_id"]), unit.kind, unit.source_code, owner)
    if unit.kind != "module":
        p.defined_symbols.update((unit.qualified_name, unit.display_name))
        if owner:
            p.defined_symbols.add(owner)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(textwrap.dedent(unit.source_code))
        _ProfileVisitor(p).visit(tree)
    except SyntaxError:
        pass
    return Profile(
        unit_key=unit.unit_key, defined_symbols=tuple(sorted(p.defined_symbols)),
        referenced_symbols=tuple(sorted(p.references)), calls=tuple(sorted(p.calls)),
        registration_keys=tuple(sorted(p.registration_keys)), flow_names=tuple(sorted(p.flow_names)),
        state_reads=tuple(sorted(p.self_fields)), related_members=tuple(sorted(p.self_calls)),
        protocol_markers=tuple(sorted(p.protocol_symbols)), owner_name=owner,
        member_name=unit.display_name if owner else "",
        ignored_calls=tuple(sorted(COMMON_CALLS)), ignored_names=tuple(sorted(COMMON_NAMES)),
        lifecycle_names=tuple(sorted(n for n in p.flow_names if _lifecycle_name(n))),
    )
