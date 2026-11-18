# b_l1_swi_glu — SwiGLU: CUDA fused activation -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement operator `SwiGlu` in AscendC.  SwiGLU is the fused
`silu(x1) * x2` gate used in transformer MLPs; the judge checks the
split/alignment rules and the dtype mix in `cases.yaml`.

Submission root: `work/submission/` with `build.sh`.  Use the CANN
vector instructions (or aclnn composition) rather than a Python
fallback; the evaluator's anti-cheat checks that the submitted kernel is
what runs.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level1/swi_glu --operator SwiGlu --device npu --no-perf --reports-dir {build}/reports
```
