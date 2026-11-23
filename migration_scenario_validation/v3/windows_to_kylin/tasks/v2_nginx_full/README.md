# v2_nginx_full — Migrate the complete nginx OS layer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Task family**: `v3` (`nginx_os`, `localization`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

nginx is being moved from Windows to Kylin V10 SP3.  The entire
target-platform operating-system layer has not been written yet.

Rebuild the OS layer as one coherent unit: process model and
daemonisation, signals and master/worker channels, the event loop and
timers, the accept/connect/read/write/sendfile paths, file and directory
handling, shared memory, atomics, time and error translation.  The Win32
implementation, the server core and modules, and the configure entry
stay visible as the reference.

Scope: the OS layer only; application modules and public module
interfaces stay unchanged.  Acceptance: configure still produces a
working server binary, it serves static content, and the selected
upstream file-serving tests pass.

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
./auto/configure --prefix={build}/nginx --without-http_rewrite_module --without-http_gzip_module && make -j
```
