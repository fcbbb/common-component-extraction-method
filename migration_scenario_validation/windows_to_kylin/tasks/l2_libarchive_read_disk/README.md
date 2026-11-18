# l2_libarchive_read_disk — libarchive read_disk: Win32 traversal -> POSIX traversal

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
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
  - sparse-file and file-type handling used by the write-disk tests.
The selected tests are the upstream read-disk tests, which run entirely
on local fixtures.

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
mkdir -p {build}/test-run && cd {build}/test-run && ../bin/libarchive_test -r {work}/libarchive/test test_read_disk test_read_disk_directory_traversals test_read_disk_entry_from_file
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
