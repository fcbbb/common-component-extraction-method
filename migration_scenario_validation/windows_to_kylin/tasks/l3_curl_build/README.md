# l3_curl_build — curl build system: VS projects -> CMake on Kylin

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The top-level CMake build system was removed; only the Visual Studio
projects and the nmake `winbuild/` files remain.  Produce a CMake build
for Kylin that:
  - builds libcurl and the `curl` tool with the target TLS/zlib dependencies
    and the bundled content;
  - generates `curl_config.h` (or an equivalent) with the feature macros
    the source expects;
  - accepts the target TLS backend and static/shared options and installs
    headers/libraries;
Do not vendor a prebuilt libcurl; the build must compile from this tree.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
