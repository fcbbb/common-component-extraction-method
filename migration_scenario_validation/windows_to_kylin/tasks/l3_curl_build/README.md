# l3_curl_build — curl build system: VS projects -> CMake on Kylin

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The top-level CMake build system was removed; only the Visual Studio
projects and the nmake `winbuild/` files remain.  Produce a CMake build
for Kylin that:
  - builds libcurl and the `curl` tool with OpenSSL, zlib and the
    bundled content;
  - generates `curl_config.h` (or an equivalent) with the feature macros
    the source expects;
  - accepts `-DCURL_USE_OPENSSL=ON -DBUILD_SHARED_LIBS=OFF` and installs
    headers/libraries;
  - runs the small TLS smoke test.
Do not vendor a prebuilt libcurl; the build must compile from this tree.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCURL_USE_OPENSSL=ON -DUSE_NGHTTP2=OFF -DCURL_USE_LIBPSL=OFF && cmake --build {build} -j
```

## Hidden tests

```bash
bash {root}/harness/tls_probe.sh --port 18444 --path {build}/src/curl
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
