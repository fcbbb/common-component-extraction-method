# b_l1_mk_mse_loss — MultiKernelBench mse_loss: CUDA model -> AscendC submission

- **Scenario**: `cuda_to_ascend`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

Migrate the mean-squared-error kernel.  The CUDA sample and the PyTorch
reference (`reference/loss/mse_loss.py`) are visible; the upstream
AscendC sample was removed.

Write `work/submission/mse_loss_submission.py` with the six source
strings described in the MultiKernelBench AscendC backend.  The kernel
must reduce over all elements, match the reference's mean convention and
dtype promotion, and pass the anti-cheat detector.

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
cd {work} && python eval_single_runner.py --input {work}/submission/mse_loss_submission.py --op mse_loss --language ascendc --result {build}/result.json && python {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating
```
