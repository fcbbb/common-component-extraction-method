# l2_libarchive_write_disk — Migrate the libarchive disk writer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`libarchive`, `implicit_contract`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/libarchive/libarchive.git @ `313aa1fa10b657de791e3202c168a6c833bc3543`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

libarchive is being moved from Windows to Kylin V10 SP3.  The
target-platform disk writer has not been written yet.

Reimplement the writer behind `archive_write_disk`: directory
creation, rename, link and symbolic-link restoration under the
overwrite, no-overwrite and secure-symlink policies; mode bits,
ownership where permitted and timestamps; sparse-file writing and
hard-link bookkeeping; and the documented error mapping for the
extract flags.  The Win32 implementation, the shared headers and
the callers stay visible as the reference.

Scope: the disk writer only; do not change the public API or the
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
