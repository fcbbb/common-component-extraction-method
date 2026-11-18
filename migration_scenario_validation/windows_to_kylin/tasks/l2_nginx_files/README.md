# l2_nginx_files — nginx file layer: Win32 file API -> POSIX file API

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/os/unix/ngx_files.c` was removed while the Win32 file layer and
`src/os/unix/ngx_files.h` stay visible.  Reimplement the POSIX file
primitives used by the whole server: open/close/read/write/pread/pwrite,
stat, rename, delete, mkdir/rmdir, symlink/readlink, timestamps,
directory iteration, path canonicalisation and the ngx_errno mapping.

The hidden test builds nginx, starts it, fetches a static file, then
runs the upstream `nginx-tests` `autoindex.t` + `range.t` suites.

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

## Hidden tests

```bash
bash {root}/harness/nginx_smoke.sh --binary {work}/objs/nginx --port 18080 && cd {work}/nginx-tests && TEST_NGINX_BINARY={work}/objs/nginx prove -I lib autoindex.t range.t
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
