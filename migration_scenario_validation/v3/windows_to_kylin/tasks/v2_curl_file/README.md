# v2_curl_file — Migrate the curl file protocol layer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`curl_file`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Components used**: file-system ×2 + `posix-file-system-request-backend-behind-a-fixed-async-42929ace`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

curl is being moved from Windows to Kylin V10 SP3.  The target-platform
FILE protocol handler has not been written yet.

Implement `lib/file.c` behind the existing `Curl_handler_file` contract:
connection setup/teardown, open/size/range/HEAD handling, URL path
decoding and the DOS/Windows drive and separator conventions the upstream
handler special-cases.  `lib/file.h`, the protocol registry and the build
entry stay visible as the reference.

Scope: the FILE handler only.  curl must build with the repository CMake
entry, read a local file, honour a byte range and a HEAD request, and
decode a percent-encoded path.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DCURL_USE_OPENSSL=ON -DUSE_NGHTTP2=OFF -DCURL_USE_LIBPSL=OFF \
  -DBUILD_CURL_EXE=ON
cmake --build {build} -j2
```

## Hidden test

`harness/file_probe.sh` reads a local file, requests a byte range,
issues HEAD and checks `Content-Length`, and fetches a percent-encoded
path containing a space.