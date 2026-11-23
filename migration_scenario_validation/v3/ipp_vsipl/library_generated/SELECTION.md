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
| Real-to-complex FFT plan and bin adapter for a streaming spectral gate (`other`) | `real-to-complex-fft-plan-and-bin-adapter-for-a-51087706` |
| split-complex FFT matched-filter correlation layer rebuilt on an opaque-plan array-view signal API (`other`) | `split-complex-fft-matched-filter-correlation-layer-d152355a` |
| Streaming complex NCO mix-and-decimate layer rebuilt from block vendor kernels onto a view-based vector signal-processing API (`other`) | `streaming-complex-nco-mix-and-decimate-layer-rebuilt-8b74d63b` |

## Using a component

- Treat the workspace headers and callers as the contract.
- Map each rule to the current names and semantics, in the current code.
- Apply the verification section to the current task's behavior.
- Use `Boundary` to decide when the method stops applying.
