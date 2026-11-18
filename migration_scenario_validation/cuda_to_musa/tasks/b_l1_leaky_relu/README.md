# b_l1_leaky_relu — MultiKernelBench leaky_relu: CUDA model -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

`prompts/cuda_model_leaky_relu.py` is the CUDA sample upstream ships;
`reference/activation/leaky_relu.py` defines `Model`, `get_inputs` and
`get_init_inputs` and is the numerical contract.  The upstream MUSA
sample has been removed from `work/` and kept in `gold/`.

Write `work/submission/leaky_relu_submission.py` defining
`class ModelNew` whose `forward` calls a custom MUSA kernel.  Build the
kernel with `torch_musa.utils.musa_extension.load_inline(...,
musa_sources=...)`; the embedded source must declare `__global__`
kernels and launch them with `<<<...>>>`.  Do not call PyTorch compute
ops for the operator body and do not reuse the reference `Model`.

The evaluator (`eval_single_runner.py --language musa`) executes the
reference and `ModelNew` on `musa:0`, compares five trials with
atol=rtol=1e-4, then times `ModelNew`.

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
cd {work} && python3 eval_single_runner.py --input {work}/submission/leaky_relu_submission.py --op leaky_relu --language musa --result {build}/result.json && python3 {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating && python3 {root}/harness/check_musa_submission.py {work}/submission/leaky_relu_submission.py
```
