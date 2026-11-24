# v2_poco_process — Migrate the Foundation process subsystem to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`poco_foundation`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component used**: `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` (process)
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

POCO Foundation is being moved from Windows to Kylin V10 SP3.  The
target-platform process subsystem has not been written yet.

Port it, using the public headers, the existing callers and the Windows
implementation as the reference.  Foundation must build with the
repository CMake entry, and `Poco::Process`, `Poco::ProcessHandle`,
`Poco::ProcessRunner` and the pipe/stdin/stdout helpers they use must keep
their documented external behavior.

Scope: the process subsystem only; do not change public headers or
signatures.  Deliverable: `libPocoFoundation.a`, built by the repository
CMake entry with Foundation enabled.

Target environment: Kylin V10 SP3, x86_64, GCC 13.3, CMake 3.16.5, libm
and the standard system threading library.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

`Foundation/src/Process_UNIX.cpp` has been removed.  Keep the public
headers and `Foundation/src/Process_WIN32U.cpp` as reference; implement
the missing platform layer and make the hidden tests pass.

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DENABLE_TESTS=ON -DENABLE_FOUNDATION=ON -DENABLE_NET=OFF -DENABLE_CRYPTO=OFF -DENABLE_NETSSL=OFF -DENABLE_JWT=OFF -DENABLE_DATA=OFF -DENABLE_MONGODB=OFF -DENABLE_REDIS=OFF -DENABLE_PROMETHEUS=OFF -DENABLE_ZIP=OFF -DENABLE_UTIL=OFF -DENABLE_XML=OFF -DENABLE_JSON=OFF -DENABLE_ENCODINGS=OFF -DENABLE_PAGECOMPILER=OFF -DENABLE_PAGECOMPILER_FILE2PAGE=OFF -DENABLE_ACTIVERECORD=OFF -DENABLE_ACTIVERECORD_COMPILER=OFF -DENABLE_CPPPARSER=OFF -DENABLE_POCODOC=OFF -DENABLE_APACHECONNECTOR=OFF -DENABLE_PDF=OFF -DENABLE_SEVENZIP=OFF -DENABLE_DATA_SQLITE=OFF -DENABLE_DATA_MYSQL=OFF -DENABLE_DATA_ODBC=OFF -DENABLE_DATA_POSTGRESQL=OFF && cmake --build {build} -j2
```

## Tests

- Hidden: `ProcessTest`, `ProcessRunnerTest` from the Foundation suite.
- Regression: `FileTest`, `PathTest`, `ThreadTest`, `SharedLibraryTest`.

## Provenance and answer separation

- Windows implementation stays visible: `Foundation/src/Process_WIN32U.cpp`.
- Target implementation is evaluator-only: `Foundation/src/Process_UNIX.cpp`
  (copied to `gold/` by `prepare.sh`, removed from `work/`).
- `Foundation/src/PipeImpl_POSIX.cpp` remains visible because pipes are a
  separate capability; this task is about process lifecycle and spawn.