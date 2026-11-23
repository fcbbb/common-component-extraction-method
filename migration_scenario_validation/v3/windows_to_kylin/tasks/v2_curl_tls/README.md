# v2_curl_tls — Migrate the curl TLS backend to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`curl_tls`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

curl is being moved from Windows to Kylin V10 SP3.  The target-platform
TLS backend has not been written yet.

Implement the backend behind curl's existing TLS abstraction: backend
registration and version reporting, certificate and hostname
verification, server name indication, ALPN, session reuse, blocking and
non-blocking handshakes integrated with the transfer state machine
(including would-block return codes), client certificates, revocation
checks and public-key pinning.  The generic TLS interface, its callers,
the Windows backend and the build entry stay visible as the reference.

Scope: the TLS backend only; do not change the generic interface or
call sites.  The library and tool must build with the repository build
entry against the platform TLS library, and a real handshake against a
local TLS server must succeed.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCURL_USE_OPENSSL=ON -DUSE_NGHTTP2=OFF -DCURL_USE_LIBPSL=OFF -DBUILD_TESTING=ON -DBUILD_CURL_EXE=ON && cmake --build {build} -j2
```
