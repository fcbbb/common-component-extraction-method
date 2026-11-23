# l2_libgit2_file — libgit2 file layer: Win32 mmap/realpath -> POSIX

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

libgit2 wraps the OS in p_* helpers.  The POSIX mmap and realpath
implementations were removed while the Win32 versions
(`src/util/win32/map.c`, `path_w32.c`, `posix_w32.c`) stay visible.

Reimplement:
  - `git__page_size`, `git__mmap`, `git__munmap` with the same GIT_MMAP_* prot/flags mapping and GIT_ENOTFOUND/GIT_EINVAL errors;
  - `p_realpath` and `p_realpath_utf8`, including the non-existing-path
    fallback that libgit2 needs for clone targets.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
