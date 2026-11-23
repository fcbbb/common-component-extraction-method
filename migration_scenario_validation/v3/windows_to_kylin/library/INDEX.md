# Transformation library index

Methodology components extracted from successful Windows→POSIX migrations. They are
project-agnostic: they describe decisions, semantic deltas, pitfalls and verification,
not any particular implementation.

## How to use

1. Identify what layer the task is missing (platform contract, file, process, thread,
   build).
2. Read `T1` first; it is the shared procedure for recovering an absent platform
   layer from visible headers and callers.
3. Read the component(s) matching the missing layer (`T2`–`T4`).
4. Use `T5` when the removed implementation is a directory or a file list rather
   than a single file, or when the build is the first symptom.
5. Combine components; they are not mutually exclusive.

## Components

| ID | Component | Use when |
|---|---|---|
| `T1` | [Platform contract recovery](components/T1/README.md) | The target platform implementation is missing but shared headers and callers remain. |
| `T2` | [File abstraction layer port](components/T2/README.md) | File I/O, stat, directory iteration, path canonicalisation, timestamps or file mapping must be rebuilt. |
| `T3` | [Process creation port](components/T3/README.md) | Process start, stdio capture, environment, working directory or exit status must be rebuilt. |
| `T4` | [Thread and synchronisation port](components/T4/README.md) | Threads, mutexes, condition variables, rwlocks or TLS wrappers must be rebuilt. |
| `T5` | [Build discovery after removal](components/T5/README.md) | Sources are selected by glob/configure and a removed directory must reappear correctly. |

## What these components do not contain

- No target-project file list, symbol list or line references.
- No implementation snippets intended for copying.
- No test names or evaluator commands.
- No task-specific build command.

The agent recovers those from the current workspace. The components tell it what to
look for and how to decide.