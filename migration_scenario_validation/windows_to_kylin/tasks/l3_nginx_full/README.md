# l3_nginx_full — nginx full OS layer: whole Win32 port -> Kylin/POSIX

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `B`
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

This is the whole-server variant: `src/os/unix/` has been removed as a
directory, not one file.  Rebuild nginx's operating-system layer for
Kylin from the Windows implementation and the rest of the tree:
  - process model, daemonisation, signals and master/worker channels;
  - event loop (epoll), timers, accept/connect/read/write/sendfile;
  - file, directory, shared memory, atomics, errno and time;
  - configuration-time detection in auto/ must still produce a working
    `objs/nginx`.
The hidden test starts nginx and runs upstream nginx-tests.

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
bash {root}/harness/nginx_smoke.sh --binary {work}/objs/nginx --port 18081 && cd {work}/nginx-tests && TEST_NGINX_BINARY={work}/objs/nginx prove -I lib autoindex.t range.t
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
