"""组件审核缓存使用的内容摘要工具。"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


CODE_ROOT = Path(__file__).resolve().parents[2]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _component_stage_source(filename: str, source: str) -> str:
    """保持组件审核缓存键与最终实验时使用的规则一致。"""
    if filename not in {
        "component_build/submission.py",
        "component_build/extraction/runner.py",
    }:
        return source
    lines = source.splitlines(keepends=True)
    excluded = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "validate_proposal_review",
            "validate_repair",
        }:
            end = node.end_lineno
            while end < len(lines) and not lines[end].strip():
                end += 1
            excluded.append((node.lineno - 1, end))
        elif (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "role"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value in {"proposal_review", "repair"}
        ):
            end = node.orelse[0].lineno - 1 if node.orelse else node.end_lineno
            excluded.append((node.lineno - 1, end))
    for start, end in sorted(excluded, reverse=True):
        del lines[start:end]
    normalized = "".join(lines)
    for roles in (
        '("extraction", "review", "repair", "proposal", "proposal_review")',
        '("extraction", "review", "repair", "proposal")',
        '("extraction", "review", "proposal", "proposal_review")',
    ):
        normalized = normalized.replace(roles, '("extraction", "review", "proposal")')
    return normalized


def code_digest(*specs: str) -> str:
    """计算模块或指定实现单元的稳定摘要。"""
    records = []
    for spec in specs:
        filename, separator, names = spec.partition(":")
        source = _component_stage_source(
            filename,
            (CODE_ROOT / filename).read_text(encoding="utf-8"),
        )
        if separator:
            selected = set(names.split(","))
            tree = ast.parse(source)
            sections = {
                node.name: ast.get_source_segment(source, node)
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name in selected
            }
            if set(sections) != selected:
                missing = selected - set(sections)
                raise ValueError(f"missing stage implementation in {filename}: {missing}")
            records.append((spec, sections))
        else:
            records.append((spec, hashlib.sha256(source.encode()).hexdigest()))
    return digest(records)
