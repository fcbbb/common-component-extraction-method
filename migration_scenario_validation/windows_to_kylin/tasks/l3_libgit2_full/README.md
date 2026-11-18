# l3_libgit2_full — libgit2 full POSIX util layer

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The complete `src/util/unix/` directory was removed (process, map,
realpath and the pthread/posix wrapper headers).  Rebuild libgit2's
POSIX utility layer so the library and its clar test suite compile and
run on Kylin.  Public libgit2 headers and call sites are unchanged; the
Win32 layer (`src/util/win32/`) stays visible as the reference.

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
cd {build} && ./util_tests -v -sfilebuf -sftruncate -sstat -spath::core -sprocess::start && ./libgit2_tests -v -xonline -sthreads::basic
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
