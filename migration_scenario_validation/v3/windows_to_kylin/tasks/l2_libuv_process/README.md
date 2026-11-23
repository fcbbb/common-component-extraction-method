# l2_libuv_process — Migrate the libuv process layer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`libuv`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/libuv/libuv.git @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`
- **License**: MIT
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

libuv is being moved from Windows to Kylin V10 SP3.  The
target-platform process backend has not been written yet.

Reimplement process spawning behind the public `uv_spawn` API:
argument and environment construction, executable lookup and
validation, the ENOENT and EACCES paths, stdio inheritance, pipe
and descriptor remapping, detached processes, process groups,
uid and gid switching, window-hide semantics, kill and
process-title helpers, and the exit and close callbacks.  The
Win32 implementation, the shared headers and the callers stay
visible as the reference.

Scope: the process backend only; do not change public headers or
signatures.  Deliverable: `libuv.a`, built by the repository
CMake entry.

Target environment: Kylin V10 SP3, x86_64, GCC 13.3, CMake
3.16.5.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The target-platform implementation has been removed.  Keep the public
headers and the Windows source as reference; implement the missing
platform layer and make the hidden tests pass.

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLIBUV_BUILD_SHARED=ON && cmake --build {build} -j2
```
