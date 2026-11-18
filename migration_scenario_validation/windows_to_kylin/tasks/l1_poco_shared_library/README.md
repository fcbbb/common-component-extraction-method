# l1_poco_shared_library — POCO SharedLibrary: LoadLibrary -> dlopen

- **Scenario**: `windows_to_kylin`
- **Level**: `L1`  **Fit**: `B`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Recreate `Foundation/src/SharedLibrary_UNIX.cpp`: load/UNLOAD shared
objects with dlopen/dlsym/dlclose, map Poco's Poco::SharedLibrary
exceptions onto dlerror(), expose prefix/suffix helpers, and keep the
symbol lookup semantics (missing symbol must throw
Poco::SharedLibrary::SymbolNotFoundException, not return null).

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DENABLE_TESTS=ON -DENABLE_FOUNDATION=ON -DENABLE_NET=OFF -DENABLE_CRYPTO=OFF -DENABLE_NETSSL=OFF -DENABLE_JWT=OFF -DENABLE_DATA=OFF -DENABLE_MONGODB=OFF -DENABLE_REDIS=OFF -DENABLE_PROMETHEUS=OFF -DENABLE_ZIP=OFF -DENABLE_UTIL=OFF -DENABLE_XML=OFF -DENABLE_JSON=OFF -DENABLE_ENCODINGS=OFF -DENABLE_PAGECOMPILER=OFF -DENABLE_PAGECOMPILER_FILE2PAGE=OFF -DENABLE_ACTIVERECORD=OFF -DENABLE_ACTIVERECORD_COMPILER=OFF -DENABLE_CPPPARSER=OFF -DENABLE_POCODOC=OFF -DENABLE_APACHECONNECTOR=OFF -DENABLE_PDF=OFF -DENABLE_SEVENZIP=OFF -DENABLE_DATA_SQLITE=OFF -DENABLE_DATA_MYSQL=OFF -DENABLE_DATA_ODBC=OFF -DENABLE_DATA_POSTGRESQL=OFF && cmake --build {build} -j
```

## Hidden tests

```bash
cd {build}/bin && LD_LIBRARY_PATH="$PWD:$LD_LIBRARY_PATH" ./Foundation-testrunner -ignore {work}/cppignore.lnx SharedLibraryTest
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
