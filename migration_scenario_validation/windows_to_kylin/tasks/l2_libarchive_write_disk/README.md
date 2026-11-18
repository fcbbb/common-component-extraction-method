# l2_libarchive_write_disk — libarchive write_disk: Win32 restore -> POSIX restore

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
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

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The target-platform implementation has been removed.  Keep the public
headers and the Windows source as reference; implement the missing
platform layer and make the hidden tests pass.

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DENABLE_TEST=ON -DENABLE_TAR=OFF -DENABLE_CPIO=OFF -DENABLE_CAT=OFF && cmake --build {build} -j
```

## Hidden tests

```bash
mkdir -p {build}/test-run && cd {build}/test-run && ../bin/libarchive_test -r {work}/libarchive/test test_write_disk test_write_disk_failures test_write_disk_perms test_write_disk_secure test_write_disk_hardlink
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
