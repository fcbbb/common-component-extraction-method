# b_l2_mk_layer_norm — MultiKernelBench layer_norm: CUDA model -> AscendC submission

- **Scenario**: `cuda_to_ascend`
- **Level**: `L2`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

Migrate layer norm, including the gamma/beta affine parameters and the
epsilon convention used by the upstream sample.  The CUDA sample and the
PyTorch reference stay visible; the AscendC sample was removed.

Write `work/submission/layer_norm_submission.py` with the six backend
strings.  `model_src` must expose `ModelNew` with the same constructor
signature as the reference (normalized shape) and must call the custom
operator, not `torch.nn.functional`.

## Workspace

```bash
bash prepare.sh
cd work
```

`work/` is the pinned upstream snapshot, minus the evaluator-only gold
files listed in `provenance.json`.  The upstream test harness is
available inside the snapshot.

## Hidden tests

```bash
cd {work} && python eval_single_runner.py --input {work}/submission/layer_norm_submission.py --op layer_norm --language ascendc --result {build}/result.json && python {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating
```
