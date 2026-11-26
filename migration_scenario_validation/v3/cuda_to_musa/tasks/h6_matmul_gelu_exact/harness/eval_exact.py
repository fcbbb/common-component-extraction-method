#!/usr/bin/env python3
"""Hidden check that distinguishes exact GELU from the tanh approximation.

The upstream harness uses a very wide softmax, which numerically hides the
activation difference.  This task evaluates the same operator on a narrow
output width, where the exact erf form and the tanh approximation diverge by
more than the accepted 1e-4 tolerance.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import torch
import torch_musa  # noqa: F401


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--result", required=True)
    args = ap.parse_args()
    result = {"compiled": False, "correctness": False, "performance": None,
              "hardware": "musa:0", "cheating": False}
    try:
        reference = _load(Path.cwd() / "reference/fuse/matmul_gelu_softmax.py", "h6_ref")
        submission = _load(Path(args.input), "h6_submission")
        # Narrow output width keeps the row softmax sensitive to the GELU
        # activation; the upstream 8192-wide case hides the difference.
        in_features, out_features = 64, 2
        torch.manual_seed(771)
        ref_model = reference.Model(in_features, out_features).to("musa")
        torch.manual_seed(771)
        new_model = submission.ModelNew(in_features, out_features).to("musa")
        missing, unexpected = new_model.load_state_dict(ref_model.state_dict(), strict=False)
        if missing or unexpected:
            raise RuntimeError(f"parameter container mismatch: missing={list(missing)} unexpected={list(unexpected)}")
        result["compiled"] = True
        for trial, scale in enumerate((0.2, 0.5, 1.0)):
            x = torch.randn(37, in_features, device="musa") * scale
            torch.musa.synchronize()
            expected = ref_model(x)
            torch.musa.synchronize()
            actual = new_model(x)
            torch.musa.synchronize()
            if expected.shape != actual.shape or not torch.allclose(expected, actual, atol=1e-4, rtol=1e-4):
                diff = (expected - actual).abs().max().item() if expected.shape == actual.shape else "shape"
                raise RuntimeError(f"trial {trial} mismatch: max_abs={diff}")
        result["correctness"] = True
    except Exception as exc:  # noqa: BLE001
        result["correctness_info"] = f"{type(exc).__name__}: {exc}"
        print(result["correctness_info"], file=sys.stderr)
    _write(Path(args.result), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
