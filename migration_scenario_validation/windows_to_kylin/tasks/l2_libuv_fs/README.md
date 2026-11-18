# l2_libuv_fs — libuv fs: Win32 OVERLAPPED I/O -> POSIX thread pool

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/libuv/libuv.git @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`
- **License**: MIT
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/unix/fs.c` was removed.  Reimplement libuv's POSIX file-system
backend against the public `uv_fs_*` API and the internal loop/req
contracts:
  - sync and async open/read/write/close, stat/lstat/fstat, mkdir,
    rmdir, unlink, rename, link, symlink, readlink, chmod, chown,
    utime, truncate, copyfile, sendfile, access and mkdtemp;
  - the thread-pool work/after-work split, req->result, uv_fs_t.path
    ownership and the documented error mapping;
  - directory scanning (uv_fs_scandir) and the fs-event/fs-poll
    integration expected by the tests.

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
cd {work} && {build}/uv_run_tests_a fs_file_async && {build}/uv_run_tests_a fs_file_sync && {build}/uv_run_tests_a fs_copyfile && {build}/uv_run_tests_a fs_stat_missing_path && {build}/uv_run_tests_a fs_readdir_non_empty_dir && {build}/uv_run_tests_a fs_scandir_empty_dir && {build}/uv_run_tests_a fs_poll && {build}/uv_run_tests_a fs_event_watch_dir
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
