# Selection guide

This bundle is a **transformation** library: it tells you how comparable migrations
were done, where they fail, and how to verify the result. It does not contain the
current task's implementation.

## Select before you write code

1. Read the task statement and the workspace headers, callers and build entry.
2. Identify which layer is missing or must be rebuilt. Do not start from the
   component list; start from the workspace.
3. For each candidate component, ask: *does the task exercise this layer, and does
   this component's "When to use" match?* If not, exclude it.
4. Always read `T1` first. It is the shared procedure for recovering a platform
   layer from the visible contract.
5. Add `T2`, `T3`, `T4` only for layers the task actually needs. Add `T5` when the
   removed implementation is a directory or a file set, or when the first symptom is
   a build/link failure.
6. Keep the selection small. A component that does not change a decision or prevent
   a known failure in this task should not be used.

## Mapping the task to components

| If the task must rebuild… | Read |
|---|---|
| An absent platform implementation behind existing headers | `T1` |
| File descriptors, metadata, directories, symlinks, timestamps, mapping | `T1`, `T2` |
| Child processes, stdio capture, environment, wait status | `T1`, `T3` |
| Threads, mutexes, condition variables, rwlocks, TLS | `T1`, `T4` |
| A removed directory or a source set picked by the build system | `T1`, `T5` |

## Using a component

- Treat the workspace headers and callers as the contract; the component only
  supplies procedure, deltas and pitfalls.
- Do not copy text or identifiers from a component into the task. Map each rule to
  the current names and semantics.
- Apply the component's verification section against the current task's behavior.
- Stop using a component when its "Boundary" section says the task is outside it.

## Selection record

The retrieval step records the chosen components in `selection.json` by bundle ID
only. The task agent reads `INDEX.md` for the selected component paths and opens each
referenced `README.md` directly.