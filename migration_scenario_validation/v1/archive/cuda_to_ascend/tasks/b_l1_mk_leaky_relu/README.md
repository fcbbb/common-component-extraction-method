# b_l1_mk_leaky_relu — MultiKernelBench leaky_relu: CUDA model -> AscendC submission

- **Scenario**: `cuda_to_ascend`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

`prompts/cuda_model_leaky_relu.py` is the CUDA/AscendC sample pair
upstream ships; the AscendC sample has been removed and only the CUDA
side plus the PyTorch reference remain.

Write `work/submission/leaky_relu_submission.py` defining the six
strings the AscendC backend consumes:
`project_json_src`, `host_tiling_src`, `host_operator_src`,
`kernel_src`, `python_bind_src`, `model_src`
(the shape used by the removed sample and by the other
`prompts/ascendc_new_model_*.py` files).

The evaluator (`eval_single_runner.py --language ascendc`) runs msopgen,
builds and installs the operator, executes the reference
`reference/activation/leaky_relu.py` against `ModelNew`, and applies the
anti-cheat detector.

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
cd {work} && python eval_single_runner.py --input {work}/submission/leaky_relu_submission.py --op leaky_relu --language ascendc --result {build}/result.json && python {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating
```
