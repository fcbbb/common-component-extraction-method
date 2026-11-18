# b_l1_exp — Exp: CUDA elementwise kernel -> Ascend C

- **Scenario**: `cuda_to_ascend`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88da922b82812f2721dd0b2fa33476`
- **License**: CANN-OSL-2.0

## Task

Implement operator `Exp` for Ascend 910B/CANN 9.1 as an AscendC kernel.

Read `tasks/level1/exp/proto.yaml` for the interface and
`tasks/level1/exp/desc.md` for the required semantics; `golden.py` is the
PyTorch reference the judge uses.  Put the operator source tree in
`work/submission/` with a `build.sh` at its root (start from
`examples/aclnn_launch_example/`).

The kernel must compute exp elementwise over the declared dtypes and
shapes, handle unaligned tails, and not fall back to PyTorch ops.  The
upstream evaluator compiles/installs the submission and checks every
case in `cases.yaml` on the NPU.

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
cd {work} && bash scripts/run_evaluation.sh --source-dir {work}/submission --task-dir {work}/tasks/level1/exp --operator Exp --device npu --no-perf --reports-dir {build}/reports
```
