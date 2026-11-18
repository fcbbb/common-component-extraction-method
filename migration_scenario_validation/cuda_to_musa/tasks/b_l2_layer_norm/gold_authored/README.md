# Project-authored positive control: `b_l2_layer_norm`

`layer_norm_submission.py` is a **project-authored** MUSA implementation, not an
upstream MultiKernelBench sample. It is evaluator-only: `prepare.sh` does not
copy it into `work/`, and agents must not see it.

## Why it exists

The pinned upstream snapshot has two conflicting contracts for this op:

| File | Contract |
|---|---|
| `prompts/cuda_model_layer_norm.py` | `x = (16384, 1024)`, `normalized_shape = 1024` |
| `reference/normalization/layer_norm.py` (used by the evaluator) | `x = (64, 64, 256, 256)`, `normalized_shape = (64, 256, 256)` |

The upstream MUSA sample `prompts/musa_new_model_layer_norm.py` follows the CUDA
prompt's 2-D contract (`rows = x.size(0)`, `cols = x.size(1)`). Against the 4-D
reference it compiles but writes only `64 x 64` values into a `zeros_like`
output, so correctness fails. A copy of that sample is kept in
[`../upstream_nonconforming/`](../upstream_nonconforming/) for the record.

Therefore the task has **no valid upstream gold**. This file fills that gap as
a positive control: it proves that the evaluator accepts a correct
4-D implementation, while remaining clearly distinguishable from upstream gold.

## Verification

Run it through the normal gold path:

```bash
python3 tools/gold_sanity.py --parent cuda_to_musa/tasks \
  --only b_l2_layer_norm --label musa_authored --no-prepare
```

Expected gate sequence: build via `mcc` -> 5 numerical trials ->
anti-cheat -> API-removal -> kernel-presence. The result is recorded in
`reports/gold_sanity/<label>/`. Verification status is tracked in
[`../../positive_controls.md`](../../positive_controls.md).

## Provenance

- Origin: project-authored for this benchmark (not upstream, not MIT-derived).
- Numerical contract: `reference/normalization/layer_norm.py` at commit
  `460a972c9be7ce18035984321d38b910e27df95f`.
- Device: MTT S4000, MUSA SDK 5.2.0, `mcc` 5.2.0.