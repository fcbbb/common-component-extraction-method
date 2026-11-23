# b_l2_rms_norm — RMSNorm: CUDA kernel -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L2`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement `RmsNorm` in AscendC: no mean subtraction, epsilon inside the
square root, optional weight.  Match the dtype and shape cases in
`tasks/level2/rms_norm/cases.yaml`.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level2/rms_norm --operator RmsNorm --device npu --no-perf --reports-dir {build}/reports
```
