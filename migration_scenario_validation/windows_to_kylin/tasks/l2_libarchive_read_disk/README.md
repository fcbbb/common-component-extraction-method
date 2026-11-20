# l2_libarchive_read_disk — libarchive read_disk: Win32 traversal -> POSIX traversal

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/libarchive/libarchive.git @ `313aa1fa10b657de791e3202c168a6c833bc3543`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`archive_read_disk_posix.c` was removed.  Reimplement the disk reader
for Kylin while keeping `archive_read_disk_windows.c` as the reference
and `archive_read_disk_private.h` unchanged:
  - ACL/xattr entry metadata (where supported), nlink, inode, device,
    symlink target and hardlink detection;
  - directory traversal with the documented visit order and the
    `descend`/`can_descend` callback contract;
  - sparse-file and file-type handling.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
