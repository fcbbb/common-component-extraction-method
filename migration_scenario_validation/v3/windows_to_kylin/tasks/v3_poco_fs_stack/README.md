# v3_poco_fs_stack — Migrate the Foundation file stack to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Task family**: `v3` (`poco_foundation`, `localization`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/demo_new_flow_v4/library/manifest.json`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

POCO Foundation is being moved from Windows to Kylin V10 SP3.  The
target-platform file stack has not been written yet: Poco::File,
Poco::FileStream, Poco::DirectoryIterator and Poco::Path have no POSIX
implementation.

Port the four missing files, using the public headers, the existing callers
and the Windows implementations as the reference.  Foundation must build with
the repository CMake entry, and the file-facing suites must keep their
documented external behavior.

The rebuilt stack must preserve the complete file contract: open, create,
read, write, copy, move, rename, remove, hard and symbolic links, timestamps,
permissions, size and space queries, file and directory classification;
buffered file streams with seek and tell; directory iteration without dot
entries; and path expansion for the current directory, the running executable
and the user's home.  `File::exists` reports false for a missing path, while
attribute queries on that path raise a Poco exception.  A new file requested
by `File::createFile` uses mode 0666 and the process umask determines the
effective permissions.

Scope: the four platform files; do not change public headers or signatures,
and do not introduce Win32 calls.  Deliverable: `libPocoFoundation.a`, built
by the repository CMake entry.

Target environment: Kylin V10 SP3, x86_64, GCC 13.3, CMake 3.16.5, libm.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The target-platform implementation has been removed.  Keep the public headers
and the Windows source as reference; implement the missing platform layer and
make the hidden tests pass.

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DENABLE_TESTS=ON -DENABLE_FOUNDATION=ON -DENABLE_NET=OFF -DENABLE_CRYPTO=OFF -DENABLE_NETSSL=OFF -DENABLE_JWT=OFF -DENABLE_DATA=OFF -DENABLE_MONGODB=OFF -DENABLE_REDIS=OFF -DENABLE_PROMETHEUS=OFF -DENABLE_ZIP=OFF -DENABLE_UTIL=OFF -DENABLE_XML=OFF -DENABLE_JSON=OFF -DENABLE_ENCODINGS=OFF -DENABLE_PAGECOMPILER=OFF -DENABLE_PAGECOMPILER_FILE2PAGE=OFF -DENABLE_ACTIVERECORD=OFF -DENABLE_ACTIVERECORD_COMPILER=OFF -DENABLE_CPPPARSER=OFF -DENABLE_POCODOC=OFF -DENABLE_APACHECONNECTOR=OFF -DENABLE_PDF=OFF -DENABLE_SEVENZIP=OFF -DENABLE_DATA_SQLITE=OFF -DENABLE_DATA_MYSQL=OFF -DENABLE_DATA_ODBC=OFF -DENABLE_DATA_POSTGRESQL=OFF && cmake --build {build} -j2
```