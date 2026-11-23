# l2_libarchive_read_disk — Migrate the libarchive disk reader to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`libarchive`, `implicit_contract`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/libarchive/libarchive.git @ `313aa1fa10b657de791e3202c168a6c833bc3543`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

libarchive is being moved from Windows to Kylin V10 SP3.  The
target-platform disk reader has not been written yet.

Reimplement the reader behind `archive_read_disk`: directory
traversal with the documented visit order and descend callbacks,
entry metadata including link count, inode, device, symbolic-link
target and hard-link detection, file-type and sparse-file
handling, and the metadata that the platform can provide.  The
Win32 implementation, the shared headers and the callers stay
visible as the reference.

Scope: the disk reader only; do not change the public API or the
shared private header.  Deliverable: `libarchive.a`, built by the
repository CMake entry.

Target environment: Kylin V10 SP3, x86_64, GCC 13.3, CMake
3.16.5.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DENABLE_TEST=ON -DENABLE_TAR=OFF -DENABLE_CPIO=OFF -DENABLE_CAT=OFF && cmake --build {build} -j2
```
