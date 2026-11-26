# Transformation library index

Methodology components extracted from completed migrations. They are
project-agnostic: rules, semantic deltas, pitfalls and verification, not
implementations.

## How to use

1. Identify which layer the task must rebuild.
2. Read every component whose `capability` matches that layer.
3. Treat the workspace contract as authoritative; the component only
   supplies the mapping procedure, deltas and pitfalls.

## Components

| ID | Component | Capability | Use when |
|---|---|---|---|
| `decode-step-cached-key-attention-rebuilt-as-custom-01481b2e` | [Decode-step cached-key attention rebuilt as custom device kernels](components/decode-step-cached-key-attention-rebuilt-as-custom-01481b2e/README.md) | `other` | Use when a caller relies on the tensor framework's fused scaled-dot-product attention over a pre-filled key/value cache, with default sca... |
| `fused-affine-projection-exact-activation-row-11f387ee` | [Fused affine projection + exact activation + row normalization rebuilt as MUSA extension kernels](components/fused-affine-projection-exact-activation-row-11f387ee/README.md) | `other` | Use this when the evaluation's compute-path policy requires every forward computation to run inside custom device kernels: tensor-library... |
| `fused-convolution-training-mode-batch-normalization-1f26f93f` | [Fused convolution, training-mode batch normalization and scalar scale as custom accelerator kernels](components/fused-convolution-training-mode-batch-normalization-1f26f93f/README.md) | `other` | Use when an eager tensor-graph layer (a 2-D convolution, then training-mode per-channel batch normalization, then a scalar multiply) must... |

## What these components do not contain

- No target-project file list, symbol list or line references.
- No implementation snippets intended for copying.
- No test names or evaluator commands.
- No current-task gold.
