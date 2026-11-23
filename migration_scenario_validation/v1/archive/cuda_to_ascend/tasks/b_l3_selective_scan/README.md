# b_l3_selective_scan — Selective scan: Mamba S6 -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L3`  **Fit**: `C`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement the Mamba selective scan recurrence for the input layouts and
dtypes in `cases.yaml`: per-step delta/A/B/C/D updates, variable sequence
lengths and the final-state output.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level4/selective_scan --operator SelectiveScan --device npu --no-perf --reports-dir {build}/reports
```
