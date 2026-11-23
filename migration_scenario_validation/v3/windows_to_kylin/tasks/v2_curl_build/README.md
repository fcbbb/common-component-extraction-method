# v2_curl_build — Migrate the curl build system to CMake on Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Task family**: `v3` (`curl_build`, `build_system`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

curl is being moved from Windows to Kylin V10 SP3.  The top-level CMake
build system has not been written yet; only the Windows project files
and the nmake build remain.

Produce a CMake build for Kylin that builds libcurl and the curl tool
with the required TLS and compression support, generates the
configuration header with the feature macros the sources expect, accepts
the documented cache options, installs headers and libraries, and
compiles entirely from this tree.  Do not vendor a prebuilt libcurl.

Scope: the build system only; the library sources stay unchanged.
Acceptance: the build succeeds with the documented options and the tool
completes a TLS request against a local TLS server.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCURL_USE_OPENSSL=ON -DUSE_NGHTTP2=OFF -DCURL_USE_LIBPSL=OFF && cmake --build {build} -j2
```
