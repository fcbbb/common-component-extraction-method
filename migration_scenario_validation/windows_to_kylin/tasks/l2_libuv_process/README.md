# l2_libuv_process — libuv process: Win32 CreateProcess -> POSIX fork/exec

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/libuv/libuv.git @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`
- **License**: MIT
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/unix/process.c` was removed.  Reimplement process spawning with the target process-spawn API and the pipe/stdio machinery:
  - uv_spawn argument and environment construction, PATH lookup,
    executable validation and the ENOENT/EACCES error paths;
  - stdio inheritance, uv_pipe_t and fd remapping, detached processes,
    process groups, uid/gid switches and windows-hide semantics;
  - uv_process_kill, uv_kill, exit/close callbacks, reaping and
    process-title helpers.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
