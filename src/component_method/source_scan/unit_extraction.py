"""将生产 Python 源码稳定切分为候选生成所需的代码单元。"""

from __future__ import annotations

from .units import CONTAINER_TYPES, method_containers, parse_units


def _line_text(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1:end])


def extract_unit_sources(files: list[dict[str, str]]) -> list[dict[str, str]]:
    """切分顶层容器、类方法及模块剩余部分，保持确定性顺序。"""
    result: list[dict[str, str]] = []
    for entry in files:
        file_id, source = entry["file_id"], entry["source_code"]
        tree, units, error = parse_units(source)
        if tree is None or units is None or error:
            if source.strip():
                result.append({"file_id": file_id, "unit_id": "module", "source_code": source})
            continue
        lines = source.splitlines(keepends=True)
        covered: list[tuple[int, int]] = []
        for node in tree.body:
            if not isinstance(node, CONTAINER_TYPES):
                continue
            decorator_rows = [item.lineno for item in getattr(node, "decorator_list", [])]
            start = min([node.lineno, *decorator_rows])
            end = node.end_lineno or node.lineno
            covered.append((start, end))
            kind = (
                "function"
                if node.__class__.__name__ in {"FunctionDef", "AsyncFunctionDef"}
                else "class"
            )
            text = _line_text(lines, start, end)
            if text.strip():
                result.append(
                    {"file_id": file_id, "unit_id": f"{kind}:{node.name}", "source_code": text}
                )
        for unit_id, node in method_containers(tree):
            decorator_rows = [item.lineno for item in getattr(node, "decorator_list", [])]
            start = min([node.lineno, *decorator_rows])
            end = node.end_lineno or node.lineno
            text = _line_text(lines, start, end)
            if text.strip():
                result.append({"file_id": file_id, "unit_id": unit_id, "source_code": text})
        module_text = "".join(
            line
            for index, line in enumerate(lines, 1)
            if not any(start <= index <= end for start, end in covered)
        )
        if module_text.strip():
            result.append({"file_id": file_id, "unit_id": "module", "source_code": module_text})
    return result


# 为流水线调用点提供稳定的内部入口。
_unit_sources = extract_unit_sources
