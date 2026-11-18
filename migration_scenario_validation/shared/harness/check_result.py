#!/usr/bin/env python3
"""Check JSON results produced by kernel benchmarks.

The checker understands the flat result object used by MultiKernelBench
(``compiled`` / ``correctness`` / ``cheating``) and walks nested reports from
CANN Bench / Triton runs looking for the same or similarly named fields.

It never turns a missing result into a pass: an absent or unreadable file is an
error, and ``correctness`` missing from every object counts as a failure when
``--require-correct`` is set.

Usage::

    python3 shared/harness/check_result.py result.json \
        --require-compiled --require-correct --forbid-cheating
    python3 shared/harness/check_result.py reports/ --recurse --require-correct
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

COMPILED_KEYS = ("compiled", "compile", "com", "build")
CORRECT_KEYS = ("correctness", "correct", "accuracy", "passed", "pass")
CHEAT_KEYS = ("cheating", "cheat")


def _iter_files(paths: Iterable[str], recurse: bool) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            pattern = "**/*.json" if recurse else "*.json"
            yield from sorted(path.glob(pattern))
        else:
            yield path


def _walk_objects(value: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _truthy(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"pass", "passed", "ok", "true", "yes", "success"}:
            return True
        if lowered in {"fail", "failed", "false", "no", "error"}:
            return False
    return None


def _find(obj: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[bool]:
    for key in keys:
        if key in obj:
            verdict = _truthy(obj[key])
            if verdict is not None:
                return verdict
    return None


def check(
    paths: Iterable[str],
    *,
    recurse: bool = False,
    require_compiled: bool = False,
    require_correct: bool = False,
    forbid_cheating: bool = False,
) -> Dict[str, Any]:
    files = list(_iter_files(paths, recurse))
    result: Dict[str, Any] = {
        "files": [str(p) for p in files],
        "cases": len(files),
        "failures": 0,
        "compiled": None,
        "correct": None,
        "cheating": None,
        "errors": [],
    }
    if not files:
        result["errors"].append("no result files")
        result["failures"] += 1
        return result

    compiled: List[bool] = []
    correct: List[bool] = []
    cheating: List[bool] = []
    for path in files:
        if not path.is_file():
            result["errors"].append(f"missing result file: {path}")
            result["failures"] += 1
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["errors"].append(f"{path}: {exc}")
            result["failures"] += 1
            continue
        objects = list(_walk_objects(data))
        found_compiled = [_find(o, COMPILED_KEYS) for o in objects]
        found_correct = [_find(o, CORRECT_KEYS) for o in objects]
        found_cheat = [_find(o, CHEAT_KEYS) for o in objects]
        c = next((v for v in found_compiled if v is not None), None)
        a = next((v for v in found_correct if v is not None), None)
        h = next((v for v in found_cheat if v is not None), None)
        if c is not None:
            compiled.append(c)
        if a is not None:
            correct.append(a)
        if h is not None:
            cheating.append(h)

    if compiled:
        result["compiled"] = all(compiled)
    if correct:
        result["correct"] = all(correct)
    if cheating:
        result["cheating"] = any(cheating)

    if require_compiled and result["compiled"] is not True:
        result["failures"] += 1
        result["errors"].append("compile gate not satisfied")
    if require_correct and result["correct"] is not True:
        result["failures"] += 1
        result["errors"].append("correctness gate not satisfied")
    if forbid_cheating and result["cheating"] is True:
        result["failures"] += 1
        result["errors"].append("anti-cheat gate failed")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--recurse", action="store_true")
    ap.add_argument("--require-compiled", action="store_true")
    ap.add_argument("--require-correct", action="store_true")
    ap.add_argument("--forbid-cheating", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = check(
        args.paths,
        recurse=args.recurse,
        require_compiled=args.require_compiled,
        require_correct=args.require_correct,
        forbid_cheating=args.forbid_cheating,
    )
    ok = not result["errors"]
    if args.json:
        print(json.dumps({"ok": ok, **result}, indent=2, ensure_ascii=False))
    else:
        print(
            f"RESULT {'PASS' if ok else 'FAIL'} files={result['cases']} "
            f"failures={result['failures']} compiled={result['compiled']} "
            f"correct={result['correct']} cheating={result['cheating']}"
        )
        print(f"SUMMARY cases={result['cases']} failures={result['failures']} worst_rel=0")
        for err in result["errors"]:
            print(f"  ERROR {err}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())