# b_l1_mse_loss — MultiKernelBench mse_loss: CUDA model -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

`prompts/cuda_model_mse_loss.py` is the CUDA sample upstream ships;
`reference/loss/mse_loss.py` defines the numerical contract.  The
upstream MUSA sample has been removed from `work/` and kept in `gold/`.

Write `work/submission/mse_loss_submission.py` defining `class ModelNew`
whose `forward` calls a custom MUSA kernel built with
`load_inline(..., musa_sources=...)`.  The embedded source must declare
`__global__` kernels and launch them with `<<<...>>>`.  The final scalar
reduction may stay in PyTorch as the upstream sample does; do not reuse
the reference `Model`.

The evaluator (`eval_single_runner.py --language musa`) runs the
reference and `ModelNew` on `musa:0` with atol=rtol=1e-4.

## Workspace

```bash
bash prepare.sh
cd work
```

`work/` is the pinned upstream snapshot, minus the evaluator-only gold
files listed in `provenance.json` and the upstream MUSA samples matched
by `prepare.remove_globs` (all `prompts/musa_new_model_*.py`).  The
upstream test harness is available inside the snapshot.

## Hidden tests

```bash
cd {work} && python3 eval_single_runner.py --input {work}/submission/mse_loss_submission.py --op mse_loss --language musa --result {build}/result.json && python3 {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating && python3 {root}/harness/check_musa_submission.py {work}/submission/mse_loss_submission.py
```
