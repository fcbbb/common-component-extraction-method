"""Stdlib-only checks mounted alongside the standalone submission checker."""

from __future__ import annotations

import ast


def validate_file_source(path, content):
    if path.suffix != ".py":
        raise ValueError(f"Python output must use a .py filename: {path}")
    compile(content, str(path), "exec")


def validate_smoke_source(code):
    tree = ast.parse(code)
    if not any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body):
        raise ValueError("each smoke-test file must define run(common)")
