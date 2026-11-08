"""组件审核缓存使用的内容摘要工具。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CODE_ROOT = Path(__file__).resolve().parents[2]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


from component_method.languages.python.controller_sources import _component_stage_source, source_sections


def code_digest(*specs: str) -> str:
    """计算模块或指定实现单元的稳定摘要。"""
    records = []
    for spec in specs:
        filename, separator, names = spec.partition(":")
        actual_filename = {
            "component_build/validation/runtime.py": "languages/python/legacy_runtime.py",
            "library_publish/component_cards.py": "languages/python/publication.py",
            "component_build/validation/service.py": "languages/python/legacy_validation.py",
            "component_build/repair/service.py": "languages/python/legacy_repair.py",
        }.get(filename, filename)
        source = _component_stage_source(
            filename,
            (CODE_ROOT / actual_filename).read_text(encoding="utf-8"),
        )
        if separator:
            selected = set(names.split(","))
            sections = source_sections(source, selected)
            if set(sections) != selected:
                missing = selected - set(sections)
                raise ValueError(f"missing stage implementation in {filename}: {missing}")
            records.append((spec, sections))
        else:
            records.append((spec, hashlib.sha256(source.encode()).hexdigest()))
    return digest(records)
