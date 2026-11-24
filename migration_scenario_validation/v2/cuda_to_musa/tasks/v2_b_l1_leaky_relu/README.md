# v2_b_l1_leaky_relu — MultiKernelBench leaky_relu: CUDA model -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L1`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT
- **Target**: musa-sdk-5.2.0 / mcc

## Task

`prompts/cuda_model_leaky_relu.py` is the CUDA sample upstream ships;
`reference/activation/leaky_relu.py` defines `Model`, `get_inputs` and
`get_init_inputs` and is the numerical contract.  The upstream MUSA
sample has been removed from `work/` and kept in `gold/`.

Write the submission file named by the task under `work/submission/`; it must define `ModelNew`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
