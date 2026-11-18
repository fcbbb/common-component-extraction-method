# b_l3_conv_2d — Conv2D: cuDNN-style convolution -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L3`  **Fit**: `C`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement `Conv2D` for the shapes in `cases.yaml`: stride, padding,
dilation, groups and bias.  The cube unit is expected; a correct
vectorised direct convolution is acceptable if it passes every case.

Submission root: `work/submission/` with `build.sh`.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level3/conv_2d --operator Conv2D --device npu --no-perf --reports-dir {build}/reports
```
