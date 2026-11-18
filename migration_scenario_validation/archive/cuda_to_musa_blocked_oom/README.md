# Archived: two `cuda_to_musa` tasks blocked by evaluator memory

`b_l2_rms_norm` and `b_l3_group_norm` were replaced in the 20-task MUSA slate
on 2026-11-16.  They are kept here, unmodified except for the move, because the
block is in the upstream evaluator, not in the task or the control:

- `reference/normalization/rms_norm.py` and
  `reference/normalization/group_norm.py` declare 2.1e9-element fp32 tensors
  (8.59 GB each).
- `utils/correctness.py` compares with `torch.allclose`, which materialises
  `|ref - new|` and the tolerance tensor in addition to both outputs and the
  input.  On a 47.90 GB MTT S4000 that OOMs at 42 GiB allocated while
  requesting 8 GiB, and even an in-place submission that aliases the input
  OOMs at 44 GiB.  `expandable_segments` does not help.
- Both tasks therefore have **no verified positive control** and cannot be
  counted.  The probes, error text and reduced-shape supplementary checks are
  in [`../../reports/gold_sanity/musa_allclose_oom/`](../../reports/gold_sanity/musa_allclose_oom/).

The two replacements in the counted slate are `b_l2_cosine_similarity_loss`
and `b_l3_conv2d_batch_norm_scaling`; both keep the evaluator's `allclose`
working set in the low gigabytes.

Do not count these two packages in the scenario totals, and do not describe
them as passing.  They can be restored if the evaluator grows a chunked
comparison or the target card exceeds ~48 GB usable VRAM.