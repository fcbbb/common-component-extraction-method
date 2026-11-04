"""S2 AST-structure signal: statement-level structural skeleton, names/constants stripped.

A skeleton stream is the ordered shape of statements (kinds + nesting brackets + a
coarse digest of each statement's main expression).  Files solving the same problem
with different variable names / literals share long skeleton runs.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from typing import Any, Iterator

from .ngrams import NgramStream, find_shared_runs
from component_method.source_scan.units import method_containers, parse_units, top_level_containers

DEFAULT_K = 3
DEFAULT_MIN_RUN = 9

_NESTED_STMT = ("body", "orelse", "handlers", "finalbody")


def expr_digest(node: ast.AST | None) -> str:
    if node is None:
        return "-"
    if isinstance(node, ast.Call):
        return "call"
    if isinstance(node, ast.BinOp):
        return "bin"
    if isinstance(node, ast.BoolOp):
        return "bool"
    if isinstance(node, ast.Compare):
        return "cmp"
    if isinstance(node, ast.UnaryOp):
        return "un"
    if isinstance(node, ast.Subscript):
        return "idx"
    if isinstance(node, ast.Attribute):
        return "attr"
    if isinstance(node, ast.Name):
        return "ref"
    if isinstance(node, ast.Constant):
        return "lit"
    if isinstance(node, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
        return "col"
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return "comp"
    if isinstance(node, ast.Lambda):
        return "lam"
    if isinstance(node, ast.JoinedStr):
        return "fstr"
    if isinstance(node, ast.IfExp):
        return "ifx"
    if isinstance(node, ast.NamedExpr):
        return "walrus"
    if isinstance(node, ast.Starred):
        return "star"
    if isinstance(node, ast.Await):
        return "await"
    if isinstance(node, ast.Yield):
        return "yield"
    return "expr"


def _stmt_token(stmt: ast.stmt) -> str | None:
    """Canonical skeleton token for one statement (None => skip)."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "def"
    if isinstance(stmt, ast.ClassDef):
        return "class"
    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            return None  # docstring
        return f"Expr:{expr_digest(stmt.value)}"
    if isinstance(stmt, ast.Assign):
        return f"Assign:{expr_digest(stmt.value)}"
    if isinstance(stmt, ast.AnnAssign):
        return f"AnnAssign:{expr_digest(stmt.value)}"
    if isinstance(stmt, ast.AugAssign):
        return f"AugAssign:{type(stmt.op).__name__}"
    if isinstance(stmt, ast.Return):
        return f"Return:{expr_digest(stmt.value)}"
    if isinstance(stmt, ast.Import):
        return "Import"
    if isinstance(stmt, ast.ImportFrom):
        return f"ImportFrom:{stmt.module or ''}"
    if isinstance(stmt, ast.If):
        return f"If:{expr_digest(stmt.test)}"
    if isinstance(stmt, ast.While):
        return f"While:{expr_digest(stmt.test)}"
    if isinstance(stmt, ast.For):
        return f"For:{expr_digest(stmt.target)}"
    if isinstance(stmt, ast.AsyncFor):
        return "AsyncFor"
    if isinstance(stmt, ast.With):
        return "With"
    if isinstance(stmt, ast.AsyncWith):
        return "AsyncWith"
    if isinstance(stmt, ast.Try):
        return "Try"
    if isinstance(stmt, ast.Raise):
        return "Raise"
    if isinstance(stmt, ast.Assert):
        return "Assert"
    if isinstance(stmt, ast.Delete):
        return "Delete"
    if isinstance(stmt, ast.Global):
        return "Global"
    if isinstance(stmt, ast.Nonlocal):
        return "Nonlocal"
    if isinstance(stmt, ast.Pass):
        return "Pass"
    if isinstance(stmt, ast.Break):
        return "Break"
    if isinstance(stmt, ast.Continue):
        return "Continue"
    if isinstance(stmt, (ast.Match,)):
        return "Match"
    return type(stmt).__name__


def _emit_block(block: list[ast.stmt]) -> Iterator[tuple[str, int]]:
    """Yield (token, row) pairs for one statement list."""
    for stmt in block:
        row = stmt.lineno
        token = _stmt_token(stmt)
        if token is None:
            continue
        yield token, row
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield "[", row
            yield from _emit_block(stmt.body)
            yield "]", row
        elif isinstance(stmt, ast.If):
            yield "[", row
            yield from _emit_block(stmt.body)
            yield "]", row
            if stmt.orelse:
                yield "else", row
                yield from _emit_block(stmt.orelse)
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            yield "[", row
            yield from _emit_block(stmt.body)
            yield "]", row
            if getattr(stmt, "orelse", None):
                yield "else", row
                yield from _emit_block(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            yield "[", row
            yield from _emit_block(stmt.body)
            yield "]", row
            for handler in stmt.handlers:
                yield "except", row
                yield "[", row
                yield from _emit_block(handler.body)
                yield "]", row
            if stmt.orelse:
                yield "else", row
                yield from _emit_block(stmt.orelse)
            if stmt.finalbody:
                yield "finally", row
                yield "[", row
                yield from _emit_block(stmt.finalbody)
                yield "]", row
        elif isinstance(stmt, ast.Match):
            yield "[", row
            for case in stmt.cases:
                yield "case", row
                yield from _emit_block(case.body)
            yield "]", row


def _container_emission(tree: ast.AST, node: ast.AST, kind: str) -> Iterator[tuple[str, int]]:
    if kind == "module":
        yield from _emit_block([n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))])
    elif kind == "function":
        yield "def", node.lineno
        yield from _emit_block(node.body)
    else:  # class
        yield "class", node.lineno
        yield "[", node.lineno
        yield from _emit_block(node.body)
        yield "]", node.lineno


def _skeleton_streams(file_id: str, source: str) -> tuple[list[NgramStream], int | None]:
    tree, units, error = parse_units(source)
    if tree is None or units is None:
        return [], error
    streams: list[NgramStream] = []
    module_tokens: list[tuple[str, int]] = []
    for node in top_level_containers(tree):
        kind = "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class"
        pairs = list(_container_emission(tree, node, kind))
        tokens = [t for t, _ in pairs]
        rows = [r for _, r in pairs]
        streams.append(NgramStream(file_id, f"{kind}:{node.name}", tokens, rows))
    for unit_id, node in method_containers(tree):
        pairs = list(_container_emission(tree, node, "function"))
        tokens = [t for t, _ in pairs]
        rows = [r for _, r in pairs]
        streams.append(NgramStream(file_id, unit_id, tokens, rows))
    pairs = list(_container_emission(tree, tree, "module"))
    tokens = [t for t, _ in pairs]
    rows = [r for _, r in pairs]
    streams.append(NgramStream(file_id, "module", tokens, rows))
    return streams, None


def cluster_evidence(file_sources: list[dict[str, str]], k: int = DEFAULT_K, min_run: int = DEFAULT_MIN_RUN) -> dict[str, Any]:
    streams: list[NgramStream] = []
    per_file_tokens: dict[str, int] = {}
    unit_tokens: dict[str, dict[str, int]] = {}
    errors: dict[str, str] = {}
    for entry in file_sources:
        file_id = entry["file_id"]
        unit_streams, error = _skeleton_streams(file_id, entry["source_code"])
        streams.extend(unit_streams)
        per_file_tokens[file_id] = sum(len(s.tokens) for s in unit_streams)
        unit_tokens[file_id] = {stream.unit_id: len(stream.tokens) for stream in unit_streams}
        if error:
            errors[file_id] = error

    runs = find_shared_runs(streams, k=k, min_run=min_run)
    pair_units: dict[tuple[str, str], dict[tuple[str, str], dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"shared_tokens": 0, "n_runs": 0})
    )
    run_counts_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for run in runs:
        if run.file_a < run.file_b:
            pair = (run.file_a, run.file_b)
            unit_pair = (run.unit_a, run.unit_b)
        else:
            pair = (run.file_b, run.file_a)
            unit_pair = (run.unit_b, run.unit_a)
        run_counts_by_pair[pair] += 1
        pair_units[pair][unit_pair]["shared_tokens"] += run.tokens
        pair_units[pair][unit_pair]["n_runs"] += 1

    pairs: list[dict[str, Any]] = []
    for (file_a, file_b), unit_evidence in pair_units.items():
        shared_tokens = sum(item["shared_tokens"] for item in unit_evidence.values())
        tokens_a, tokens_b = per_file_tokens.get(file_a, 0), per_file_tokens.get(file_b, 0)
        pairs.append({
            "file_a": file_a,
            "file_b": file_b,
            "shared_tokens": shared_tokens,
            "n_runs": run_counts_by_pair[(file_a, file_b)],
            "tokens_a": tokens_a,
            "tokens_b": tokens_b,
            "containment": round(shared_tokens / max(min(tokens_a, tokens_b), 1), 4),
            "unit_pairs": [
                {
                    "file_a": file_a,
                    "unit_a": unit_a,
                    "file_b": file_b,
                    "unit_b": unit_b,
                    "shared_tokens": item["shared_tokens"],
                    "n_runs": item["n_runs"],
                    "tokens_a": unit_tokens.get(file_a, {}).get(unit_a, 0),
                    "tokens_b": unit_tokens.get(file_b, {}).get(unit_b, 0),
                    "containment": round(
                        item["shared_tokens"]
                        / max(
                            min(
                                unit_tokens.get(file_a, {}).get(unit_a, 0),
                                unit_tokens.get(file_b, {}).get(unit_b, 0),
                            ),
                            1,
                        ),
                        4,
                    ),
                }
                for (unit_a, unit_b), item in unit_evidence.items()
            ],
        })
    pairs.sort(key=lambda p: p["shared_tokens"], reverse=True)
    return {
        "signal": "skeleton",
        "k": k,
        "min_run": min_run,
        "per_file_tokens": per_file_tokens,
        "unit_tokens": unit_tokens,
        "parse_errors": errors,
        "pairs": pairs,
        "unit_pairs": [item for pair in pairs for item in pair["unit_pairs"]],
    }
