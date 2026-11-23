# v2_nginx_files — Migrate the nginx file layer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`nginx_os`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

nginx is being moved from Windows to Kylin V10 SP3.  The target-platform
file layer has not been written yet.

Reimplement the file abstraction used by the whole server: file opening
and closing, sequential and positioned I/O, metadata queries, rename and
deletion, directory creation and iteration, symbolic links, timestamp
updates, path canonicalisation and error-code translation.  The module
headers, the server core, the Win32 implementation and the configure
entry stay visible as the reference.

Scope: the file layer only; do not change module interfaces or build
configuration.  Acceptance: nginx builds with its own configure entry,
serves static content, passes the selected upstream file-serving tests,
and satisfies the I/O, directory and timestamp contract of the rebuilt
layer.

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
