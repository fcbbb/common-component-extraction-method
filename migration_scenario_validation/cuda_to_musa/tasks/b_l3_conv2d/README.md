# b_l3_conv2d — Conv2D: cuDNN-style convolution -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L3`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

`reference/convolution/conv_standard_2d_square_input_square_kernel.py`
is the upstream operator contract.  MultiKernelBench does not ship a
per-op CUDA sample for this operator at the pinned commit; the CUDA side
is a direct convolution.

Write `work/submission/conv_standard_2d_square_input_square_kernel_submission.py`
defining `class ModelNew` whose `forward` calls a custom MUSA kernel
built with `load_inline(..., musa_sources=...)`.  The embedded source
must declare `__global__` kernels and launch them with `<<<...>>>`; do
not fall back to `muDNN`/`torch.nn.Conv2d` for the operator body and do
not reuse `Model`.

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
cd {work} && python3 eval_single_runner.py --input {work}/submission/conv_standard_2d_square_input_square_kernel_submission.py --op conv_standard_2d_square_input_square_kernel --language musa --result {build}/result.json && python3 {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating && python3 {root}/harness/check_musa_submission.py {work}/submission/conv_standard_2d_square_input_square_kernel_submission.py
```
