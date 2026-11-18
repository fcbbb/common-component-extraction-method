# b_l2_mk_standard_matmul — MultiKernelBench standard matrix multiplication

- **Scenario**: `cuda_to_ascend`
- **Level**: `L2`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

Implement `standard_matrix_multiplication` as an AscendC operator using
the cube unit or a vector-tiled fallback.  The reference
(`reference/matmul/standard_matrix_multiplication.py`) defines the
transpose flags, dtypes and bias handling.

Write `work/submission/standard_matrix_multiplication_submission.py`
with the six backend strings.  The anti-cheat detector rejects a
submission whose `ModelNew` calls `torch.matmul`.

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
cd {work} && python eval_single_runner.py --input {work}/submission/standard_matrix_multiplication_submission.py --op standard_matrix_multiplication --language ascendc --result {build}/result.json && python {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating
```
