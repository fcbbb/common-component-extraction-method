# l2_libgit2_process — libgit2 process/thread layer: Win32 process + pthread wrappers

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The POSIX process spawner and the pthread wrapper header were removed.
Recreate `src/util/unix/process.c`, `pthread.h` and `posix.h` with the
same interfaces the rest of libgit2 uses:
  - git__process_init / git__process_cleanup
  - git__spawn with the stdout/stderr redirection and environment
    hooks used by the process tests
  - thread, mutex, rwlock, cond and TLS wrappers including timed waits
    and the cleanup destructors
The Win32 files remain as the behavioural reference; do not change the
call sites under src/.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=ON -DBUILD_CLI=OFF -DUSE_SSH=OFF -DUSE_HTTPS=OFF -DUSE_BUNDLED_ZLIB=ON -DREGEX_BACKEND=builtin && cmake --build {build} -j
```

## Hidden tests

```bash
cd {build} && ./util_tests -v -sprocess::start && ./libgit2_tests -v -sthreads::basic -sthreads::tlsdata
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
