#!/usr/bin/env python3
"""Generic Python-side evaluator for kernel/operator migration tasks.

Supports the three source kinds used in the CUDA -> Ascend scenario:

``multikernelbench``
    ``source/`` holds the CUDA implementation, ``reference/`` the PyTorch
    model, ``gold/`` the Ascend C reference.  The candidate is
    ``work/candidate.py`` (or ``--candidate``) exposing ``ModelNew``.

``cannbench``
    ``spec/`` holds ``proto.yaml``, ``desc.md``, ``golden.py`` and
    ``cases.yaml``; the candidate is an Ascend C project or a Python module.

``triton``
    ``source/`` is a Triton kernel; the candidate is the Ascend-tuned version.

Without an Ascend device the script runs the reference only and reports
``correct: skipped``; it never fabricates a pass.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

try:
    from . import caseio
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from shared.harness import caseio  # type: ignore


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _first(task: Dict[str, Any], key: str, subdirs: List[str]) -> Optional[Path]:
    root = Path(task["_root"])
    source = task.get("source") or {}
    for item in source.get(key) or []:
        rel = str(item)
        for sub in subdirs:
            candidate = root / sub / rel
            if candidate.is_file():
                return candidate
            candidate = root / sub / Path(rel).name
            if candidate.is_file():
                return candidate
    return None


def _torch():
    try:
        import torch  # type: ignore

        return torch
    except Exception:  # noqa: BLE001
        return None


def _flatten(value: Any) -> Any:
    torch = _torch()
    if torch is not None and isinstance(value, torch.Tensor):
        return value.detach().float().cpu().tolist()
    if isinstance(value, (list, tuple)):
        return [_flatten(v) for v in value]
    return value


def _cases(task: Dict[str, Any], ref_mod: Any) -> List[Dict[str, Any]]:
    root = Path(task["_root"])
    for relative in (
        Path("harness") / "cases.json",
        Path("harness") / "cases.yaml",
        Path("tests") / "cases.yaml",
        Path("spec") / "cases.yaml",
    ):
        candidate = root / relative
        if not candidate.is_file():
            continue
        if candidate.suffix == ".json":
            return caseio.read_cases(candidate)
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or []
        if isinstance(data, dict):
            data = data.get("cases", [])
        rows = [c for c in data if isinstance(c, dict)]
        if rows and "input_shape" in rows[0]:
            return [_cannbench_case(row) for row in rows]
        return rows
    if ref_mod is not None and hasattr(ref_mod, "get_inputs"):
        return [{"name": "case_0", "inputs": ref_mod.get_inputs()}]
    return [{"name": "case_0", "inputs": []}]


_DTYPES = {
    "float16": "float16",
    "fp16": "float16",
    "bfloat16": "bfloat16",
    "bf16": "bfloat16",
    "float32": "float32",
    "fp32": "float32",
}


def _cannbench_case(row: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a CANN Bench ``cases.yaml`` row into concrete torch inputs.

    The tensors are built lazily in ``_materialize`` because torch may be
    unavailable on the machine that only inspects the package.
    """
    shapes = row.get("input_shape") or []
    if shapes and not isinstance(shapes[0], (list, tuple)):
        shapes = [shapes]
    dtypes = row.get("dtype") or ["float32"]
    if not isinstance(dtypes, (list, tuple)):
        dtypes = [dtypes]
    value_range = row.get("value_range") or [-1, 1]
    return {
        "name": f"case_{row.get('case_id', 0)}",
        "shapes": [list(shape) for shape in shapes],
        "dtypes": list(dtypes),
        "kwargs": dict(row.get("attrs") or {}),
        "value_range": list(value_range)[:2],
        "_torch_inputs": True,
    }


def _materialize(case: Dict[str, Any], torch: Any, device: str, seed: int) -> Any:
    if not case.get("_torch_inputs"):
        return case.get("inputs", [])
    shapes = case.get("shapes") or []
    dtypes = case.get("dtypes") or ["float32"]
    lo, hi = (case.get("value_range") or [-1, 1])[:2]
    tensors = []
    for index, shape in enumerate(shapes):
        dtype_name = dtypes[min(index, len(dtypes) - 1)]
        dtype = getattr(torch, _DTYPES.get(str(dtype_name).lower(), "float32"))
        generator = torch.Generator(device="cpu").manual_seed(seed + index)
        tensor = torch.empty(shape, dtype=torch.float32, device="cpu").uniform_(
            float(lo), float(hi), generator=generator
        )
        tensors.append(tensor.to(dtype=dtype, device=device))
    return tensors


def _op_name(task: Dict[str, Any]) -> Optional[str]:
    for item in (task.get("source") or {}).get("spec_files") or []:
        path = Path(task["_root"]) / "spec" / Path(str(item)).name
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        operator = data.get("operator") if isinstance(data, dict) else None
        if isinstance(operator, dict) and operator.get("name"):
            return str(operator["name"])
    return task.get("op_name")


def _as_inputs(torch: Any, inputs: Any, device: str) -> Any:
    if torch is None:
        return inputs
    if isinstance(inputs, (list, tuple)):
        return [_as_inputs(torch, x, device) for x in inputs]
    if isinstance(inputs, (int, float, list)):
        try:
            return torch.tensor(inputs, dtype=torch.float32, device=device)
        except Exception:  # noqa: BLE001
            return inputs
    return inputs


def _snake(name: str) -> str:
    out: List[str] = []
    for index, ch in enumerate(name):
        if ch.isupper() and index and not name[index - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _golden_callable(module: Any, op_name: Optional[str]) -> Any:
    if op_name:
        for candidate in (op_name, _snake(op_name), op_name.lower()):
            func = getattr(module, candidate, None)
            if callable(func):
                return func
    func = getattr(module, "golden", None)
    if callable(func):
        return func
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if callable(value) and getattr(value, "__module__", None) == module.__name__:
            return value
    return None


def _call_model(
    module: Any,
    inputs: Any,
    device: str,
    kwargs: Optional[Dict[str, Any]] = None,
    op_name: Optional[str] = None,
) -> Any:
    torch = _torch()
    inputs = _as_inputs(torch, inputs, device)
    kwargs = dict(kwargs or {})
    if hasattr(module, "ModelNew"):
        model = module.ModelNew()
    elif hasattr(module, "Model"):
        model = module.Model()
    elif callable(_golden_callable(module, op_name)):
        return _golden_callable(module, op_name)(
            *(inputs if isinstance(inputs, (list, tuple)) else [inputs]), **kwargs
        )
    else:
        raise AttributeError("module has no ModelNew / Model / operator function")
    if torch is not None and hasattr(model, "to"):
        model = model.to(device)
    if torch is not None and hasattr(model, "eval"):
        model.eval()
    with torch.no_grad() if torch is not None else _nullcontext():
        args = inputs if isinstance(inputs, (list, tuple)) else [inputs]
        return model(*args, **kwargs)


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def run(
    task_root: str,
    *,
    device: str = "cpu",
    candidate: Optional[str] = None,
    cases_path: Optional[str] = None,
    allow_skip: bool = False,
) -> Dict[str, Any]:
    root = Path(task_root).resolve()
    with (root / "task.yaml").open("r", encoding="utf-8") as fh:
        task = yaml.safe_load(fh) or {}
    task["_root"] = str(root)
    kind = str(task.get("source_kind") or "multikernelbench")
    result: Dict[str, Any] = {
        "task": task.get("task_id", root.name),
        "source_kind": kind,
        "device": device,
        "compile": "skipped",
        "run": "skipped",
        "correct": "skipped",
        "cases": 0,
        "failures": 0,
        "worst_rel": 0.0,
    }

    torch = _torch()
    if torch is None:
        result["error"] = "torch is not installed"
        result["status"] = "skipped" if allow_skip else "error"
        return result

    ref_path = _first(task, "reference_files", ["reference", "spec", "source"])
    if ref_path is None:
        result["error"] = "no reference file found"
        result["status"] = "error"
        return result
    ref_mod = _load_module(ref_path, f"{result['task']}_ref")
    result["reference"] = str(ref_path)

    cases_list = _cases(task, ref_mod)
    if cases_path:
        cases_list = caseio.read_cases(cases_path)
    result["cases"] = len(cases_list)

    ref_outputs: List[Any] = []
    op_name = _op_name(task)
    for index, case in enumerate(cases_list):
        inputs = _materialize(case, torch, "cpu", 1234 + index)
        try:
            ref_outputs.append(
                _flatten(
                    _call_model(
                        ref_mod,
                        inputs,
                        "cpu",
                        kwargs=case.get("kwargs"),
                        op_name=op_name,
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            result["correct"] = "fail"
            result["error"] = f"reference failed: {exc}"
            result["status"] = "fail"
            return result
    result["run"] = "ok"

    cand_path = Path(candidate) if candidate else root / "work" / "candidate.py"
    if not cand_path.is_file():
        result["correct"] = "skipped"
        result["reason"] = f"candidate not found: {cand_path}"
        result["status"] = "skipped" if allow_skip else "fail"
        return result

    cand_mod = _load_module(cand_path, f"{result['task']}_cand")
    result["candidate"] = str(cand_path)
    failures = 0
    worst = 0.0
    for index, (case, expected) in enumerate(zip(cases_list, ref_outputs)):
        inputs = _materialize(case, torch, device, 1234 + index)
        try:
            got = _flatten(
                _call_model(
                    cand_mod,
                    inputs,
                    device,
                    kwargs=case.get("kwargs"),
                    op_name=op_name,
                )
            )
            verdict = caseio.compare(got, expected)
            worst = max(worst, float(verdict["worst_rel"]))
            if not verdict["ok"]:
                failures += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            result.setdefault("case_errors", []).append({"case": index, "error": str(exc)})
    result["failures"] = failures
    result["worst_rel"] = worst
    result["correct"] = "pass" if failures == 0 else "fail"
    result["status"] = "pass" if failures == 0 else "fail"
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-root", required=True)
    ap.add_argument("--device", choices=["cpu", "npu"], default="cpu")
    ap.add_argument("--candidate", default=None)
    ap.add_argument("--cases", default=None)
    ap.add_argument("--allow-skip", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        result = run(
            args.task_root,
            device=args.device,
            candidate=args.candidate,
            cases_path=args.cases,
            allow_skip=args.allow_skip,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "pass" else (3 if result.get("status") == "skipped" else 1)


if __name__ == "__main__":
    raise SystemExit(main())