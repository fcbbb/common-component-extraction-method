# b_l2_cross_entropy_loss — CrossEntropyLoss: CUDA fused loss -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L2`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement `CrossEntropyLoss` (log-softmax + NLL, with the reduction modes,
ignore index and optional weight from `proto.yaml`).  Numerical stability
for fp16 logits is part of the test.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level2/cross_entropy_loss --operator CrossEntropyLoss --device npu --no-perf --reports-dir {build}/reports
```
