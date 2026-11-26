# Selection guide

This is a transformation library: it records how comparable migrations were
done, where they fail, and how to verify the result. It does not contain the
current task's implementation.

## Select before you write code

1. Read the task statement and the workspace contract.
2. Identify which layer is missing, then consult the component list.
3. Keep the components whose `When to use` matches the task.
4. Use a component when it changes a decision or prevents a known failure.

## Mapping the task to components

| If the task must rebuild... | Read |
|---|---|
| Decode-step cached-key attention rebuilt as custom device kernels (`other`) | `decode-step-cached-key-attention-rebuilt-as-custom-01481b2e` |
| Fused affine projection + exact activation + row normalization rebuilt as MUSA extension kernels (`other`) | `fused-affine-projection-exact-activation-row-11f387ee` |
| Fused convolution, training-mode batch normalization and scalar scale as custom accelerator kernels (`other`) | `fused-convolution-training-mode-batch-normalization-1f26f93f` |

## Using a component

- Treat the workspace headers and callers as the contract.
- Map each rule to the current names and semantics, in the current code.
- Apply the verification section to the current task's behavior.
- Use `Boundary` to decide when the method stops applying.
