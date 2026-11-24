# v2_b_l2_cosine_similarity_loss — Cosine similarity loss: CUDA norms + dot + mean -> MUSA kernel

- **Scenario**: `cuda_to_musa`
- **Level**: `L2`
- **Source**: https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7ce18035984321d38b910e27df95f`
- **License**: MIT
- **Target**: musa-sdk-5.2.0 / mcc

## Task

`reference/loss/cosine_similarity_loss.py` is the upstream operator
contract.  It takes two (128, 4096) float32 tensors and returns the
scalar `mean(1 - F.cosine_similarity(predictions, targets, dim=1))`;
the default `eps=1e-8` clamps each row norm before the division.

Write the submission file named by the task under `work/submission/`; it must define `ModelNew`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
