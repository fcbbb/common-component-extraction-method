# b_l1_mse_loss — MultiKernelBench mse_loss: CUDA model -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L1`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT
- **Target**: musa-sdk-5.2.0 / mcc

## Task

`prompts/cuda_model_mse_loss.py` is the CUDA sample upstream ships;
`reference/loss/mse_loss.py` defines the numerical contract.  The
upstream MUSA sample has been removed from `work/` and kept in `gold/`.

Write the submission file named by the task under `work/submission/`; it must define `ModelNew`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
