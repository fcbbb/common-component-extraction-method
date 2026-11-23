#!/usr/bin/env python3
"""Kernel-presence gate for CUDA -> MUSA submissions.

The upstream MultiKernelBench MUSA backend reports ``cheating=False`` for every
submission, so ``check_result.py --forbid-cheating`` cannot catch a ``ModelNew``
that simply calls the reference ``Model`` or PyTorch compute ops.  This gate
adds the checks that do not need a GPU:

* the submission defines ``class ModelNew`` with its own ``forward``;
* it imports/creates a MUSA extension via ``load_inline(...)`` and passes
  ``musa_sources``;
* the embedded source declares ``__global__`` and launches a kernel with
  ``<<<...>>>``;
* ``forward`` calls a function of that extension and returns a value derived
  from the call;
* ``ModelNew`` never references the upstream reference ``Model``.

It is deliberately a presence/alias check, not a proof that the kernel
implements every floating-point op.  A submission that adds a dummy kernel and
does the math in Python still passes this gate; that limitation is recorded in
``v1/cuda_to_musa/design.md``.

Usage::

    python3 shared/harness/check_musa_submission.py work/submission/op_submission.py
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _self_attr(node: ast.AST) -> Optional[str]:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _kernel_assignments(tree: ast.AST) -> Dict[str, str]:
    """Map ``self.<attr>`` to the name bound from ``load_inline(...)``."""
    inline_names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if _call_name(value) == "load_inline":
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        inline_names.add(target.id)

    attrs: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            if node.value.id in inline_names:
                for target in node.targets:
                    attr = _self_attr(target)
                    if attr:
                        attrs[attr] = node.value.id
    return attrs


def _extension_calls(forward: ast.AST, inline_names: set[str], attrs: Dict[str, str]) -> List[ast.Call]:
    calls: List[ast.Call] = []
    for node in ast.walk(forward):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        base = func.value
        if isinstance(base, ast.Attribute):
            attr = _self_attr(base)
            if attr in attrs:
                calls.append(node)
        elif isinstance(base, ast.Name) and base.id in inline_names:
            calls.append(node)
    return calls


def _returned(call: ast.Call, forward: ast.AST) -> bool:
    returns = [n for n in ast.walk(forward) if isinstance(n, ast.Return) and n.value is not None]
    for ret in returns:
        if any(node is call for node in ast.walk(ret.value)):
            return True
    # Accept ``y = ext.fn(...); return y``.
    assigned: Dict[str, ast.Call] = {}
    for node in ast.walk(forward):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
    for ret in returns:
        if isinstance(ret.value, ast.Name) and assigned.get(ret.value.id) is call:
            return True
    return False


def check_text(text: str, *, source_name: str = "<submission>") -> Dict[str, Any]:
    errors: List[str] = []
    result: Dict[str, Any] = {
        "source": source_name,
        "ok": False,
        "errors": errors,
        "inline_names": [],
        "self_attrs": {},
        "kernel_calls": 0,
    }

    for marker in ("musa_sources", "__global__", "<<<"):
        if marker not in text:
            errors.append(f"missing MUSA kernel marker: {marker!r}")
    if "load_inline" not in text:
        errors.append("missing load_inline(...) extension build")

    try:
        tree = ast.parse(text, filename=source_name)
    except SyntaxError as exc:
        errors.append(f"cannot parse submission as Python: {exc}")
        return result

    attrs = _kernel_assignments(tree)
    inline_names = set(attrs.values())
    result["inline_names"] = sorted(inline_names)
    result["self_attrs"] = dict(attrs)
    if not inline_names:
        errors.append("no load_inline(...) result is stored (expected e.g. 'ext = load_inline(...)')")

    model_new = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModelNew"),
        None,
    )
    if model_new is None:
        errors.append("missing class ModelNew")
        return result
    methods = {n.name: n for n in model_new.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    forward = methods.get("forward")
    if forward is None:
        errors.append("ModelNew has no forward method")

    for node in ast.walk(model_new):
        if isinstance(node, ast.Name) and node.id == "Model":
            errors.append("ModelNew references the upstream reference Model")
            break

    if forward is not None and inline_names:
        calls = _extension_calls(forward, inline_names, attrs)
        result["kernel_calls"] = len(calls)
        if not calls:
            errors.append("ModelNew.forward does not call the compiled MUSA extension")
        elif not any(_returned(call, forward) for call in calls):
            errors.append("ModelNew.forward does not return a value derived from the extension call")

    result["ok"] = not errors
    return result


def check_file(path: str) -> Dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        return {
            "source": str(source),
            "ok": False,
            "errors": [f"submission not found: {source}"],
            "inline_names": [],
            "self_attrs": {},
            "kernel_calls": 0,
        }
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "source": str(source),
            "ok": False,
            "errors": [f"cannot read {source}: {exc}"],
            "inline_names": [],
            "self_attrs": {},
            "kernel_calls": 0,
        }
    return check_text(text, source_name=str(source))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("submission", help="path to <op>_submission.py")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = check_file(args.submission)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"MUSA_SUBMISSION={'PASS' if result['ok'] else 'FAIL'}")
        for error in result["errors"]:
            print(f"  ERROR {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())