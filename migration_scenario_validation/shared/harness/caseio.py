#!/usr/bin/env python3
"""Small, dependency-free case container shared by the scenarios.

The IPP -> VSIPL packages already use a compact binary format for C tests.
New packages can use this JSON container instead; it is readable by both the
C/C++ and Python harnesses and keeps the hidden cases in one place.

Format::

    {"magic": "MBCASE1", "version": 1, "cases": [
        {"name": "case_0", "inputs": [...], "expected": [...]},
        ...
    ]}
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MAGIC = "MBCASE1"
VERSION = 1


def write_cases(path: str | Path, cases: Iterable[Dict[str, Any]]) -> None:
    payload = {"magic": MAGIC, "version": VERSION, "cases": list(cases)}
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def read_cases(path: str | Path) -> List[Dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("magic") != MAGIC:
        raise ValueError(f"{path}: bad magic (expected {MAGIC})")
    if int(data.get("version", 0)) != VERSION:
        raise ValueError(f"{path}: unsupported version {data.get('version')!r}")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"{path}: 'cases' must be a list")
    return cases


def _close(a: Any, b: Any, rtol: float, atol: float) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, rtol, atol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(float(a)) and math.isnan(float(b)):
            return True
        return abs(float(a) - float(b)) <= atol + rtol * abs(float(b))
    return a == b


def compare(
    got: Any,
    expected: Any,
    *,
    rtol: float = 1e-4,
    atol: float = 1e-5,
) -> Dict[str, Any]:
    """Compare nested lists/scalars and return a JSON-friendly verdict."""
    flattened_got: List[float] = []
    flattened_exp: List[float] = []

    def walk(x: Any, y: Any) -> None:
        if isinstance(x, (list, tuple)) and isinstance(y, (list, tuple)):
            if len(x) != len(y):
                raise ValueError(f"shape mismatch: {len(x)} vs {len(y)}")
            for a, b in zip(x, y):
                walk(a, b)
            return
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            flattened_got.append(float(x))
            flattened_exp.append(float(y))
            return
        if x != y:
            raise ValueError(f"value mismatch: {x!r} vs {y!r}")

    walk(got, expected)
    worst = 0.0
    for a, b in zip(flattened_got, flattened_exp):
        denom = max(abs(b), 1e-30)
        worst = max(worst, abs(a - b) / denom if abs(b) > atol else abs(a - b))
    return {
        "ok": all(_close(a, b, rtol, atol) for a, b in zip(flattened_got, flattened_exp)),
        "count": len(flattened_got),
        "worst_rel": worst,
        "rtol": rtol,
        "atol": atol,
    }


def summarize(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    items = list(results)
    failures = [item for item in items if not item.get("ok")]
    worst = max((float(item.get("worst_rel", 0.0)) for item in items), default=0.0)
    return {
        "cases": len(items),
        "failures": len(failures),
        "worst_rel": worst,
        "ok": not failures,
    }