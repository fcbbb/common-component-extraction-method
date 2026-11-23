# b_l2_top_k — TopK: CUDA selection kernel -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L2`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement `TopK` returning values and indices for the largest `k`
elements along the declared dimension.  The judge checks index validity
as well as values, and includes `k` values close to the axis size.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level3/top_k --operator TopK --device npu --no-perf --reports-dir {build}/reports
```
