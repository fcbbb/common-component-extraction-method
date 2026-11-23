# b_l1_softmax — Softmax: CUDA row softmax -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement `Softmax` in AscendC.  The interesting cases are the large
`dim` sizes and the fp16/bf16 inputs where a naive exp overflows; the
judge compares against `golden.py` with the tolerance in `cases.yaml`.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level2/softmax --operator Softmax --device npu --no-perf --reports-dir {build}/reports
```
