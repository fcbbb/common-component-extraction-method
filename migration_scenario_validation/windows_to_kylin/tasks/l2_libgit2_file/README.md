# l2_libgit2_file — libgit2 file layer: Win32 mmap/realpath -> POSIX

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

libgit2 wraps the OS in p_* helpers.  The POSIX mmap and realpath
implementations were removed while the Win32 versions
(`src/util/win32/map.c`, `path_w32.c`, `posix_w32.c`) stay visible.

Reimplement:
  - `git__page_size`, `git__mmap`, `git__munmap` on top of
    sysconf(_SC_PAGE_SIZE), mmap/munmap, with the same
    GIT_MMAP_* prot/flags mapping and GIT_ENOTFOUND/GIT_EINVAL errors;
  - `p_realpath` and `p_realpath_utf8` via realpath(3), including the
    non-existing-path fallback that libgit2 needs for clone targets.

Tests selected from the util suite exercise file buffers, truncation,
stat and path canonicalisation.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=ON -DBUILD_CLI=OFF -DUSE_SSH=OFF -DUSE_HTTPS=OFF -DUSE_BUNDLED_ZLIB=ON -DREGEX_BACKEND=builtin && cmake --build {build} -j
```

## Hidden tests

```bash
cd {build} && ./util_tests -v -sfilebuf -sftruncate -sstat -spath::core
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
