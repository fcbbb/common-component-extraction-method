# v2_curl_thread — Migrate the curl threaded resolver to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`curl_thread`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component used**: `portable-threading-and-synchronisation-backend-for-an-96ad6495` (threading)
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

curl is being moved from Windows to Kylin V10 SP3.  The target-platform
thread primitives that its threaded DNS resolver is built on have not
been written yet.

Implement `lib/curl_threads.c` behind the contract in
`lib/curl_threads.h`.  The header keeps both the POSIX and the Win32 type
mappings visible as the reference; `lib/asyn-thread.c`, the synchronous
resolver and the c-ares alternate stay visible too.

This port retires the Windows target: the translation unit must contain
only the POSIX implementation.  The Windows branch is not to be
reintroduced — no `windows.h`, `HANDLE`, `CreateThread`,
`_beginthreadex`, `WaitForSingleObject` or `CloseHandle` anywhere in
`lib/curl_threads.c`; `harness/check_api_removal.sh` scans that file for
them.

Scope: the thread primitive translation unit only.  The tool must build
with `ENABLE_THREADED_RESOLVER=ON`, report `AsynchDNS`, and complete a
real request whose hostname is resolved on the resolver thread.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DCURL_USE_OPENSSL=OFF -DUSE_NGHTTP2=OFF -DCURL_USE_LIBPSL=OFF \
  -DENABLE_THREADED_RESOLVER=ON -DBUILD_CURL_EXE=ON
cmake --build {build} -j2
```

## Hidden test

`harness/thread_probe.sh` checks `curl --version` for `AsynchDNS`, serves a
file on `127.0.0.1:18086`, then fetches it through the `localhost` hostname
so the resolver thread has to run before the request completes.