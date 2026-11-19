# l2_libarchive_write_disk — libarchive write_disk: Win32 restore -> POSIX restore

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/libarchive/libarchive.git @ `313aa1fa10b657de791e3202c168a6c833bc3543`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`archive_write_disk_posix.c` was removed.  Reimplement restore-to-disk
on Kylin, keeping the Win32 implementation as the reference:
  - mkdir/rename/link/symlink with overwrite, no-overwrite and
    secure-symlink policies;
  - mode bits, ownership where permitted, timestamps, ACL/xattr flags;
  - sparse file writing and hardlink bookkeeping;
  - the documented error mapping for EEXIST/EPERM/ENOTSUP and the
    `ARCHIVE_EXTRACT_*` flags.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
