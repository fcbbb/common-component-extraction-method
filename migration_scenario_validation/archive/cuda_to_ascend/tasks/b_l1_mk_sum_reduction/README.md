# b_l1_mk_sum_reduction — MultiKernelBench sum reduction over a dimension

- **Scenario**: `cuda_to_ascend`
- **Level**: `L1`  **Fit**: `B`
- **Source kind**: `upstream-kernel-benchmark`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT

## Task

Implement `sum_reduction_over_a_dimension` as an AscendC operator.  The
reference is `reference/reduce/sum_reduction_over_a_dimension.py`; the
reference signature (including the `dim` and `keepdim` arguments) is the
contract.

Write `work/submission/sum_reduction_over_a_dimension_submission.py`
with the six backend strings.  Handle non-contiguous reduction axes by
tiling rather than by materialising a transposed tensor through PyTorch.

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
cd {work} && python eval_single_runner.py --input {work}/submission/sum_reduction_over_a_dimension_submission.py --op sum_reduction_over_a_dimension --language ascendc --result {build}/result.json && python {root}/harness/check_result.py {build}/result.json --require-compiled --require-correct --forbid-cheating
```
