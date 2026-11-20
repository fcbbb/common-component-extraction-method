# l2_libuv_fs — libuv fs: Win32 OVERLAPPED I/O -> POSIX thread pool

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
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
    integration.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
