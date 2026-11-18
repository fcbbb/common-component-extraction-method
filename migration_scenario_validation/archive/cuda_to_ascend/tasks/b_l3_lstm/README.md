# b_l3_lstm — LSTM: cuDNN RNN cell -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L3`  **Fit**: `C`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement the LSTM operator (single/multi-layer and bidirectional modes
from `proto.yaml`) with the gate ordering and initial-state semantics of
the PyTorch reference.  Sequence lengths vary per case.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level4/lstm --operator LSTM --device npu --no-perf --reports-dir {build}/reports
```
