#!/usr/bin/env python3
"""Hidden evaluator: conv -> training BatchNorm -> scale with non-identity affine.

The upstream evaluator leaves BatchNorm's affine parameters at their default
identity values, so a kernel that silently drops gamma/beta still passes.
This task exercises the layer contract instead: both models receive the same
non-identity affine parameters before comparison, and one input is a
non-contiguous NCHW view.  The reference source and submission remain the
upstream/gold-authored files; only the hidden check is task-specific.
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
        work = Path.cwd()
        reference = _load(work / "reference/fuse/conv2d_batch_norm_scaling.py", "h5_ref")
        submission = _load(Path(args.input), "h5_submission")
        torch.manual_seed(2309)
        init_inputs = reference.get_init_inputs()
        ref_model = reference.Model(*init_inputs).to("musa")
        # Force a non-identity affine transform.  The reference and the
        # rebuilt model must consume the same parameters.
        with torch.no_grad():
            ref_model.bn.weight.copy_(torch.linspace(0.75, 1.75, ref_model.bn.weight.numel(), device="musa"))
            ref_model.bn.bias.copy_(torch.linspace(-0.4, 0.6, ref_model.bn.bias.numel(), device="musa"))
        torch.manual_seed(2309)
        new_model = submission.ModelNew(*init_inputs).to("musa")
        state = ref_model.state_dict()
        missing, unexpected = new_model.load_state_dict(state, strict=False)
        if missing or unexpected:
            raise RuntimeError(f"parameter container mismatch: missing={list(missing)} unexpected={list(unexpected)}")
        result["compiled"] = True

        base = reference.get_inputs()[0]
        inputs = [base, base.transpose(2, 3).contiguous().transpose(2, 3)]
        with torch.no_grad():
            for index, x in enumerate(inputs):
                x = x.to("musa")
                torch.musa.synchronize()
                expected = ref_model(x)
                torch.musa.synchronize()
                actual = new_model(x)
                torch.musa.synchronize()
                if expected.shape != actual.shape or not torch.allclose(expected, actual, atol=1e-4, rtol=1e-4):
                    diff = (expected - actual).abs().max().item() if expected.shape == actual.shape else "shape"
                    raise RuntimeError(f"trial {index} mismatch: max_abs={diff}")
        result["correctness"] = True
    except Exception as exc:  # noqa: BLE001
        result["correctness_info"] = f"{type(exc).__name__}: {exc}"
        print(result["correctness_info"], file=sys.stderr)
    _write(Path(args.result), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
