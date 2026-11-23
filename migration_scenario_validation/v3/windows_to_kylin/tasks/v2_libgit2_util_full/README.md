# v2_libgit2_util_full — Migrate the complete libgit2 utility layer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Task family**: `v3` (`libgit2_util`, `localization`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

libgit2 is being moved from Windows to Kylin V10 SP3.  The entire
target-platform utility layer has not been written yet: process
creation, memory mapping, path canonicalisation, directory handling,
error translation and the thread/synchronisation wrappers shared by the
rest of the library.

Rebuild the layer as one coherent unit, using the visible headers, the
callers and the Windows implementation as the reference.  The library
and its selected offline utility and threading suites must build and
pass with the repository CMake entry.

Scope: the utility layer only; public libgit2 headers and call sites
stay unchanged.  Deliverable: `libgit2.a`.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=ON -DBUILD_CLI=OFF -DUSE_SSH=OFF -DUSE_HTTPS=OFF -DUSE_BUNDLED_ZLIB=ON -DREGEX_BACKEND=builtin && cmake --build {build} -j2
```
