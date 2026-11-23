# b_l2_mk_cumsum — MultiKernelBench cumsum: CUDA scan -> AscendC submission

- **Scenario**: `cuda_to_ascend`
- **Level**: `L2`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

Implement `cumsum` (inclusive prefix sum) along the dimension used by
`reference/math/cumsum.py`.  A naive per-row loop is acceptable as a
starting point; the judge checks values, dtype and shape.

Write `work/submission/cumsum_submission.py` with the six backend
strings.

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
cd {work} && python eval_single_runner.py --input {work}/submission/cumsum_submission.py --op cumsum --language ascendc --result {build}/result.json && python {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating
```
