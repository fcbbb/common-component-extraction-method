# v2_b_l2_layer_norm — MultiKernelBench layer_norm: CUDA model -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L2`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT
- **Target**: musa-sdk-5.2.0 / mcc

## Task

`prompts/cuda_model_layer_norm.py` is the CUDA sample upstream ships;
`reference/normalization/layer_norm.py` defines the numerical contract.
The upstream MUSA sample was written against a different (2-D) input
contract and is not a valid answer here; it is removed from `work/`.

Write the submission file named by the task under `work/submission/`; it must define `ModelNew`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
