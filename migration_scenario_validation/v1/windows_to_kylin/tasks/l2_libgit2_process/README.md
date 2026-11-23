# l2_libgit2_process — libgit2 process/thread layer: Win32 process + pthread wrappers

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The POSIX process spawner and the pthread wrapper header were removed.
Recreate `src/util/unix/process.c`, `pthread.h` and `posix.h` with the
same interfaces the rest of libgit2 uses:
  - git__process_init / git__process_cleanup
  - git__spawn with the stdout/stderr redirection and environment
    hooks
  - thread, mutex, rwlock, cond and TLS wrappers including timed waits
    and the cleanup destructors
The Win32 files remain as the behavioural reference; do not change the
call sites under src/.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
