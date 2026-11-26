#!/usr/bin/env python3
"""Hidden check: decode attention over an arbitrary (non-contiguous) KV cache.

The source contract is `F.scaled_dot_product_attention` on rank-3 Q/K/V.
Caches in real serving paths are often transposed or sliced views; the
submission must normalize them without changing values.  The key length is
deliberately not a multiple of the reduction block.
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
        reference = _load(Path.cwd() / "reference/attention/kv_cached_attention_inference.py", "h7_ref")
        submission = _load(Path(args.input), "h7_submission")
        torch.manual_seed(913)
        ref_model = reference.Model().to("musa")
        new_model = submission.ModelNew().to("musa")
        result["compiled"] = True

        batch, q_len, keys, width = 1, 1, 257, 64
        q = torch.randn(batch, q_len, width, device="musa")
        # Build K/V as transposed views: values are a (batch, width, keys)
        # tensor viewed as (batch, keys, width), so the last-axis stride is not 1.
        k = torch.randn(batch, width, keys, device="musa").transpose(1, 2)
        v = torch.randn(batch, width, keys, device="musa").transpose(1, 2)
        with torch.no_grad():
            torch.musa.synchronize()
            expected = ref_model(q, k, v)
            torch.musa.synchronize()
            actual = new_model(q, k, v)
            torch.musa.synchronize()
        if expected.shape != actual.shape or not torch.allclose(expected, actual, atol=1e-4, rtol=1e-4):
            diff = (expected - actual).abs().max().item() if expected.shape == actual.shape else "shape"
            raise RuntimeError(f"non-contiguous cache mismatch: max_abs={diff}")
        result["correctness"] = True
    except Exception as exc:  # noqa: BLE001
        result["correctness_info"] = f"{type(exc).__name__}: {exc}"
        print(result["correctness_info"], file=sys.stderr)
    _write(Path(args.result), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
