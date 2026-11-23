# Upstream MUSA sample that does not match this task's contract

`musa_new_model_layer_norm.py` is a verbatim copy of the pinned upstream sample
`prompts/musa_new_model_layer_norm.py` (MultiKernelBench commit
`460a972c9be7ce18035984321d38b910e27df95f`, MIT).

It is kept here only as evidence and must not be used as a gold answer.

## Why it is not a valid control

The upstream repository ships two different contracts for `layer_norm`:

- `prompts/cuda_model_layer_norm.py`: `x = (16384, 1024)` (2-D).
- `reference/normalization/layer_norm.py`, which the evaluator imports:
  `x = (64, 64, 256, 256)` with `normalized_shape = (64, 256, 256)`.

The sample consumes `rows = x.size(0)` and `cols = x.size(1)` and writes
`rows * cols` values into `torch::zeros_like(x)`. On the 4-D reference it fills
only `64 x 64` of the `64 x 64 x 256 x 256` output, so it compiles but is
numerically wrong.

Hardware record (2026-11-16, MTT S4000, MUSA SDK 5.2.0, `mcc` 5.2.0,
torch 2.11.0.post1, torch_musa 2.11.0.post1+b431668):

```text
RESULT FAIL files=1 failures=1 compiled=True correct=False cheating=False
```

The replacement positive control is
[`../gold_authored/layer_norm_submission.py`](../gold_authored/layer_norm_submission.py).