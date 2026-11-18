# b_l3_conv2d_batch_norm_scaling — Conv2d + BatchNorm2d (batch stats) + scale: fused CUDA model -> MUSA kernels

- **Scenario**: `cuda_to_musa`
- **Level**: `L3`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

`reference/fuse/conv2d_batch_norm_scaling.py` is the upstream operator
contract: `nn.Conv2d(8, 64, 3)` on a (128, 8, 128, 128) float32 input,
then `nn.BatchNorm2d(64)` in training mode (per-channel mean and biased
variance over N*H*W, eps=1e-5, affine weight/bias), then a multiply by
the scaling factor (2.0).  The model is constructed from
`get_init_inputs() = [8, 64, 3, 2.0]` and the evaluator re-seeds before
constructing `ModelNew`, so an `nn.Conv2d` parameter container with the
same shape gets the same weights.

Write `work/submission/conv2d_batch_norm_scaling_submission.py` defining
`class ModelNew` whose `forward` calls custom MUSA kernels built with
`load_inline(..., musa_sources=...)`.  The embedded source must declare
`__global__` kernels and launch them with `<<<...>>>`; do not fall back
to `muDNN`/`torch.nn.Conv2d` or `torch.nn.functional.batch_norm` for the
operator body and do not reuse `Model`.

Precision: this torch_musa build enables muDNN TF32 by default, so the
reference `nn.Conv2d` is ~5e-4 off exact fp32.  Set
`torch.backends.mudnn.allow_tf32 = False` at module level and compute the
convolution in fp32; the harness compares at atol=rtol=1e-4.

The evaluator (`eval_single_runner.py --language musa`) runs the
reference and `ModelNew` on `musa:0`.

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
cd {work} && python3 eval_single_runner.py --input {work}/submission/conv2d_batch_norm_scaling_submission.py --op conv2d_batch_norm_scaling --language musa --result {build}/result.json && python3 {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating && python3 {root}/harness/check_musa_submission.py {work}/submission/conv2d_batch_norm_scaling_submission.py
```
