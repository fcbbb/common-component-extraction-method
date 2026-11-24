# Component x task capability matrix

- library manifest: `/home/fcbbbb/projects/demo_common_exreaction/common-component-extraction-method/repository/migration_scenario_validation/v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- components: 5
- task packages scanned: 25

`primary` means the task title or source file names name an operation in
the component's capability family (file / process / thread / build).
`secondary` candidates are shown as review material only: they are
ranked by operation-term overlap and IDF-weighted API tokens found in
the task's source-side `work/` tree, and do not count as coverage.

## Per task

### `l2_libarchive_read_disk` (archives, 669 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 8.0 | 22.27 | `archive`, `directory`, `disk`, `file`, `link`, `metadata`; `st_dev`x12, `st_ino`x13, `SEEK_DATA`x2 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 8.0 | 19.47 | `archive`, `directory`, `disk`, `file`, `link`, `metadata`; `SUID`x5, `ACLs`x26, `SGID`x4 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 6.0 | 9.06 | `directory`, `file`, `link`, `metadata`; `ENOENT`x13, `EOPNOTSUPP`x9, `FD_CLOEXEC`x2 |

### `l2_libarchive_write_disk` (archives, 669 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 9.0 | 18.09 | `archive`, `directory`, `disk`, `file`, `link`, `rename`; `ACLs`x25, `SUID`x4, `SGID`x3 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 8.0 | 22.27 | `archive`, `directory`, `disk`, `file`, `link`, `symlink`; `st_dev`x12, `st_ino`x13, `SEEK_DATA`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 7.0 | 8.96 | `directory`, `file`, `link`, `rename`, `symlink`; `ENOENT`x13, `EOPNOTSUPP`x8, `FD_CLOEXEC`x2 |

### `l2_libuv_fs` (async-io, 356 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 21.0 | 14.60 | `access`, `chmod`, `chown`, `close`, `directory`, `file`; `IOV_MAX`x4, `ENOENT`x9, `EPERM`x6 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 15.0 | 10.44 | `access`, `close`, `directory`, `file`, `link`, `lstat`; `st_dev`x5, `st_ino`x5, `ENOENT`x9 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 15.0 | 1.52 | `chmod`, `close`, `directory`, `file`, `link`, `open`; `ACLs`x1 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 6.0 | 2.92 | `close`, `cmake`, `file`, `link`, `read`, `write`; `CPUs`x3, `x86_64`x1 |

### `l2_libuv_process` (async-io, 356 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` | process | primary | 11.0 | 0.00 | `close`, `descriptor`, `exit`, `kill`, `path`, `pipe` |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 6.0 | 15.61 | `close`, `descriptor`, `exit`, `path`, `process`, `spawn`; `IOV_MAX`x4, `copy_file_range`x2, `ENOENT`x8 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 5.0 | 10.88 | `close`, `descriptor`, `exit`, `path`, `process`; `st_dev`x6, `st_ino`x6, `ENOENT`x8 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 4.0 | 2.92 | `close`, `cmake`, `path`, `process`; `CPUs`x3, `x86_64`x1 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | secondary | 4.0 | 1.52 | `close`, `descriptor`, `path`, `process`; `ACLs`x1 |

### `l2_libuv_thread` (runtime, 356 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | primary | 10.0 | 2.92 | `barrier`, `cmake`, `condition`, `lock`, `pool`, `semaphore`; `CPUs`x3, `x86_64`x1 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 3.0 | 16.62 | `lock`, `pool`, `thread`; `IOV_MAX`x4, `copy_file_range`x2, `ENOENT`x9 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 1.0 | 10.98 | `condition`; `st_dev`x6, `st_ino`x6, `ENOENT`x9 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | secondary | 1.0 | 1.52 | `thread`; `ACLs`x1 |

### `l2_opencv_highgui` (gui, 0 source files)

_No materialized `work/`; the matrix cannot inspect this package._

### `negative_win32_eventlog` (negative, 2904 source files)

_No primary candidate; secondary matches listed for review._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 3.0 | 5.14 | `file`, `stat`, `write`; `ENOENT`x7, `EPERM`x3, `EOPNOTSUPP`x1 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 3.0 | 4.09 | `cmake`, `file`, `write`; `CPUs`x5, `x86_64`x2 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 3.0 | 2.47 | `file`, `stat`, `write`; `ENOENT`x7 |

### `v2_curl_build` (build-system, 884 source files)

_No primary candidate; secondary matches listed for review._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 5.0 | 1.74 | `build`, `cmake`, `compile`, `file`, `tls`; `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 3.0 | 1.97 | `build`, `compile`, `file`; `FD_CLOEXEC`x1, `EOPNOTSUPP`x1 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | secondary | 3.0 | 1.52 | `build`, `compile`, `file`; `ACLs`x1 |

### `v2_curl_tls` (networking, 884 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | primary | 4.0 | 1.74 | `build`, `tls`; `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 1.0 | 1.97 | `build`; `FD_CLOEXEC`x1, `EOPNOTSUPP`x1 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | secondary | 1.0 | 1.52 | `build`; `ACLs`x1 |

### `v2_file` (filesystem, 2903 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 5.0 | 4.66 | `build`, `file`, `filesystem`; `ENOENT`x6, `EPERM`x2, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 5.0 | 2.34 | `build`, `file`, `filesystem`; `ENOENT`x6 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 5.0 | 0.00 | `build`, `file`, `filesystem` |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 3.0 | 4.09 | `build`, `cmake`, `file`; `CPUs`x5, `x86_64`x2 |

### `v2_foundation_full` (runtime, 2887 source files)

_No primary candidate; secondary matches listed for review._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 2.0 | 4.09 | `build`, `cmake`; `CPUs`x5, `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 1.0 | 3.71 | `build`; `ENOENT`x4, `EPERM`x1, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 1.0 | 2.00 | `build`; `ENOENT`x4 |

### `v2_libgit2_util_full` (vcs, 1115 source files)

_No primary candidate; secondary matches listed for review._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 5.0 | 5.05 | `build`, `directory`, `path`, `process`, `thread`; `ENOENT`x14, `FD_CLOEXEC`x1, `EPERM`x1 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 5.0 | 1.90 | `build`, `cmake`, `path`, `process`, `thread`; `CPUs`x3 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 4.0 | 12.03 | `build`, `directory`, `path`, `process`; `st_dev`x8, `st_ino`x7, `ENOENT`x14 |

### `v2_nginx_files` (networking, 391 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 10.0 | 10.68 | `build`, `directory`, `file`, `link`, `metadata`, `open`; `IOV_MAX`x6, `FD_CLOEXEC`x3, `EPERM`x2 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 10.0 | 0.00 | `build`, `directory`, `file`, `link`, `metadata`, `open` |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 9.0 | 2.75 | `build`, `directory`, `file`, `link`, `metadata`, `open`; `ENOENT`x2, `st_ino`x1 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 4.0 | 1.53 | `build`, `file`, `link`, `path`; `CPUs`x2 |

### `v2_nginx_full` (networking, 327 source files)

_No primary candidate; secondary matches listed for review._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 9.0 | 2.75 | `atomic`, `directory`, `file`, `path`, `process`, `read`; `FD_CLOEXEC`x2, `ENOENT`x1 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 8.0 | 1.53 | `atomic`, `file`, `path`, `process`, `read`, `signal`; `CPUs`x2 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 6.0 | 0.84 | `directory`, `file`, `path`, `process`, `read`, `write`; `ENOENT`x1 |

### `v2_nginx_process` (process, 388 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` | process | primary | 6.0 | 0.00 | `build`, `process`, `signal`, `spawn` |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 5.0 | 10.23 | `build`, `process`, `signal`, `spawn`, `worker`; `IOV_MAX`x6, `FD_CLOEXEC`x2, `EPERM`x2 |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 4.0 | 1.53 | `build`, `process`, `signal`, `worker`; `CPUs`x2 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 2.0 | 2.75 | `build`, `process`; `ENOENT`x2, `st_ino`x1 |

### `v2_nginx_thread` (threading, 389 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | primary | 11.0 | 1.53 | `build`, `condition`, `lock`, `mutex`, `pool`, `signal`; `CPUs`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 6.0 | 10.68 | `build`, `lock`, `pool`, `signal`, `thread`, `worker`; `IOV_MAX`x6, `FD_CLOEXEC`x3, `EPERM`x2 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 2.0 | 2.75 | `build`, `condition`; `ENOENT`x2, `st_ino`x1 |

### `v2_path` (filesystem, 2903 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 5.0 | 5.14 | `build`, `filesystem`, `path`; `ENOENT`x7, `EPERM`x3, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 5.0 | 2.47 | `build`, `filesystem`, `path`; `ENOENT`x7 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 5.0 | 0.00 | `build`, `filesystem`, `path` |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 3.0 | 4.09 | `build`, `cmake`, `path`; `CPUs`x5, `x86_64`x2 |

### `v2_poco_process` (process, 2904 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` | process | primary | 6.0 | 0.00 | `build`, `pipe`, `process`, `thread` |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 4.0 | 4.09 | `build`, `cmake`, `process`, `thread`; `CPUs`x5, `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 3.0 | 5.14 | `build`, `process`, `thread`; `ENOENT`x7, `EPERM`x3, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 2.0 | 2.47 | `build`, `process`; `ENOENT`x7 |

### `v2_rwlock_semaphore` (runtime, 2902 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | primary | 7.0 | 4.09 | `build`, `cmake`, `lock`, `semaphore`, `thread`; `CPUs`x5, `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 3.0 | 5.14 | `build`, `lock`, `thread`; `ENOENT`x7, `EPERM`x3, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 1.0 | 2.47 | `build`; `ENOENT`x7 |

### `v2_shared_library` (runtime, 2903 source files)

_No primary candidate; secondary matches listed for review._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 2.0 | 4.09 | `build`, `cmake`; `CPUs`x5, `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 1.0 | 5.14 | `build`; `ENOENT`x7, `EPERM`x3, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 1.0 | 2.47 | `build`; `ENOENT`x7 |

### `v2_thread` (runtime, 2903 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | primary | 5.0 | 4.09 | `build`, `cmake`, `thread`; `CPUs`x5, `x86_64`x2 |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | secondary | 2.0 | 5.14 | `build`, `thread`; `ENOENT`x7, `EPERM`x3, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | secondary | 1.0 | 2.47 | `build`; `ENOENT`x7 |

### `v3_poco_fs_stack` (filesystem, 2900 source files)

| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 16.0 | 4.66 | `build`, `copy`, `directory`, `file`, `filesystem`, `link`; `ENOENT`x6, `EPERM`x2, `EOPNOTSUPP`x1 |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 15.0 | 2.34 | `build`, `copy`, `directory`, `file`, `filesystem`, `link`; `ENOENT`x6 |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 15.0 | 0.00 | `build`, `directory`, `file`, `filesystem`, `link`, `open` |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | secondary | 9.0 | 4.09 | `build`, `cmake`, `copy`, `file`, `link`, `path`; `CPUs`x5, `x86_64`x2 |

### `v2_curl_thread` (no domain, planned)

_Planned package: scored from title, notes and source file names only._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | primary | 3.0 | 0.00 | `thread` |

### `v2_curl_file` (no domain, planned)

_Planned package: scored from title, notes and source file names only._


| component | capability | tier | ops | api | evidence |
|---|---|:--:|---:|---:|---|
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | primary | 3.0 | 0.00 | `file` |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | primary | 3.0 | 0.00 | `file` |
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | primary | 3.0 | 0.00 | `file` |

### `synthetic_multi_call_site` (no domain, planned)

_No candidate component._

## Per component

| component | capability | tasks |
|---|---|---|
| `posix-file-system-request-backend-behind-a-fixed-async-42929ace` | file-system/io | `l2_libuv_fs`, `v2_nginx_files`, `l2_libarchive_read_disk`, `l2_libarchive_write_disk`, `v2_path`, `v2_file`, `v3_poco_fs_stack`, `v2_curl_file` |
| `archive-extraction-writer-win32-handle-attribute-model-a927554a` | file-system/metadata | `l2_libarchive_read_disk`, `l2_libarchive_write_disk`, `l2_libuv_fs`, `v2_file`, `v2_nginx_files`, `v2_path`, `v3_poco_fs_stack`, `v2_curl_file` |
| `filesystem-disk-reader-backend-descriptor-relative-100f4548` | file-system/metadata | `l2_libarchive_read_disk`, `l2_libarchive_write_disk`, `l2_libuv_fs`, `v2_nginx_files`, `v2_path`, `v2_file`, `v3_poco_fs_stack`, `v2_curl_file` |
| `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` | process | `l2_libuv_process`, `v2_nginx_process`, `v2_poco_process` |
| `portable-threading-and-synchronisation-backend-for-an-96ad6495` | threading | `v2_rwlock_semaphore`, `v2_thread`, `l2_libuv_thread`, `v2_curl_tls`, `v2_nginx_thread`, `v2_curl_thread` |

## Coverage

- components serving >=2 tasks: 5 `posix-file-system-request-backend-behind-a-fixed-async-42929ace`, `archive-extraction-writer-win32-handle-attribute-model-a927554a`, `filesystem-disk-reader-backend-descriptor-relative-100f4548`, `process-spawn-backend-for-an-event-loop-win32-handle-c7216288`, `portable-threading-and-synchronisation-backend-for-an-96ad6495`
- tasks with >=2 components: 8 `l2_libarchive_read_disk`, `l2_libarchive_write_disk`, `l2_libuv_fs`, `v2_file`, `v2_nginx_files`, `v2_path`, `v3_poco_fs_stack`, `v2_curl_file`
- tasks with no candidate: `l2_opencv_highgui`, `negative_win32_eventlog`, `v2_curl_build`, `v2_foundation_full`, `v2_libgit2_util_full`, `v2_nginx_full`, `v2_shared_library`, `synthetic_multi_call_site`
- components with no task: none
