# h3_sdpa_mask — Scaled dot-product attention -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L3`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT
- **Target**: musa-sdk-5.2.0 / mcc

## Task

`reference/attention/scaled_dot_product_attention.py` is the upstream
operator contract.  MultiKernelBench does not ship a per-op CUDA sample
for this operator at the pinned commit; the CUDA side is a fused
scaled dot-product attention.

Write the submission file named by the task under `work/submission/`; it must define `ModelNew`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
