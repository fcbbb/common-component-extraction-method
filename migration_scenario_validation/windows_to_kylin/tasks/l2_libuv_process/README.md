# l2_libuv_process — libuv process: Win32 CreateProcess -> POSIX fork/exec

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/libuv/libuv.git @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`
- **License**: MIT
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/unix/process.c` was removed.  Reimplement process spawning with
fork/exec and the pipe/stdio machinery the tests expect:
  - uv_spawn argument and environment construction, PATH lookup,
    executable validation and the ENOENT/EACCES error paths;
  - stdio inheritance, uv_pipe_t and fd remapping, detached processes,
    process groups, uid/gid switches and windows-hide semantics;
  - uv_process_kill, uv_kill, exit/close callbacks, reaping and
    process-title helpers.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLIBUV_BUILD_SHARED=ON && cmake --build {build} -j
```

## Hidden tests

```bash
cd {work} && {build}/uv_run_tests_a spawn_stdout && {build}/uv_run_tests_a spawn_stdin && {build}/uv_run_tests_a spawn_exit_code && {build}/uv_run_tests_a spawn_and_kill && {build}/uv_run_tests_a spawn_detached && {build}/uv_run_tests_a spawn_reads_child_path && {build}/uv_run_tests_a spawn_relative_path && {build}/uv_run_tests_a process_title && {build}/uv_run_tests_a process_priority
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
