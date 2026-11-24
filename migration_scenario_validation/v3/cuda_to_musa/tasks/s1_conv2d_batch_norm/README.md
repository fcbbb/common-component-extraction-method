# s1_conv2d_batch_norm — Conv2d + BatchNorm2d (batch stats) + scale: fused CUDA model -> MUSA kernels

- **Scenario**: `cuda_to_musa`
- **Level**: `L3`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT
- **Target**: musa-sdk-5.2.0 / mcc

## Task

`reference/fuse/conv2d_batch_norm_scaling.py` is the upstream operator
contract: `nn.Conv2d(8, 64, 3)` on a (128, 8, 128, 128) float32 input,
then `nn.BatchNorm2d(64)` in training mode (per-channel mean and biased
variance over N*H*W, eps=1e-5, affine weight/bias), then a multiply by
the scaling factor (2.0).  The model is constructed from
`get_init_inputs() = [8, 64, 3, 2.0]`; an `nn.Conv2d` parameter container with
the same shape gets the same weights.

Write the submission file named by the task under `work/submission/`; it must define `ModelNew`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
