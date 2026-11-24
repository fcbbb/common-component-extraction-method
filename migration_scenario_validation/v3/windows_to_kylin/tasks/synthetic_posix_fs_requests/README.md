# synthetic_posix_fs_requests — asynchronous file-system request backend

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `C`  **Counted**: no (reported separately)
- **Task family**: `v3` (`synthetic_posix_fs_requests`, `synthetic`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component exercised**: `posix-file-system-request-backend-behind-a-fixed-async-42929ace`
- **Source**: `synthetic://windows-to-posix/async-fs-requests` (project-authored)
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

A small asynchronous file-system library keeps its public request model, its
shared request layer and its worker pool.  Only the platform backend exists
for Windows (`src/win32/afs_win32.c`); the POSIX backend
(`src/posix/afs_posix.c`) must be written.

The request model is fixed: a submission without a callback runs inline and
returns the result, a submission with a callback is queued on the worker pool,
returns 0 and completes on a worker thread.  Results are non-negative counts
or descriptors, and failures are `-(errno)` with the positive `errno` in the
request.

Scope: the platform translation unit only.

## Workspace

```bash
bash prepare.sh
cd work
```

## Build and checks

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release
cmake --build {build} -j2
{build}/afs_selftest {work}
```

The hidden probe compiles its checks against `libafs.a` and exercises vector
limits, interrupted transfers, positioned I/O, the error convention,
asynchronous worker-thread execution and descriptor inheritance.