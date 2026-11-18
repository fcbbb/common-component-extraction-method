# l2_curl_tls — curl TLS backend: Schannel/Win32 -> OpenSSL on Kylin

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The OpenSSL vtls backend was removed; the Schannel backend and the
generic `vtls` interface stay visible.  Implement `lib/vtls/openssl.c`
against the OpenSSL 3.x API:
  - the `Curl_ssl` backend vtable and version reporting;
  - certificate and hostname verification, SNI, ALPN, session reuse;
  - blocking and non-blocking handshakes with the curl connect state
    machine, including the "want read/want write" return codes;
  - client certificates, CRL and pinned public key hooks used by the
    curl test suite.

The hidden test builds curl with `CURL_USE_OPENSSL=ON`, then checks a
real TLS handshake against a local `openssl s_server`.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCURL_USE_OPENSSL=ON -DUSE_NGHTTP2=OFF -DCURL_USE_LIBPSL=OFF -DBUILD_TESTING=ON -DBUILD_CURL_EXE=ON && cmake --build {build} -j
```

## Hidden tests

```bash
bash {root}/harness/tls_probe.sh --port 18443 --path {build}/src/curl
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
