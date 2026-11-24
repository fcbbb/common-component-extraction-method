# v2_nginx_thread — Migrate the nginx thread primitives to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`nginx_os`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component used**: `portable-threading-and-synchronisation-backend-for-an-96ad6495` (threading)
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5` (release-1.26.3)
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

nginx is being moved from Windows to Kylin V10 SP3.  The threading primitives
used by the core thread pool have not been written yet.

Reimplement the mutex, condition variable and thread-id primitives behind the
contract declared in `src/os/unix/ngx_thread.h`.  The header, the thread pool
(`src/core/ngx_thread_pool.c`), the Win32 implementation and the configure
entry stay visible as the reference.

Scope: the threading primitives only; do not change the pool, the interfaces
or the build configuration.  Deliverable: `objs/nginx`, built with
`--with-threads`.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The three Unix primitive sources are removed; `ngx_thread.h` and
`src/core/ngx_thread_pool.c` remain visible.

## Build

```bash
./auto/configure --prefix={build}/nginx --with-threads --without-http_rewrite_module --without-http_gzip_module && make -j
```

## Tests

- Hidden: an evaluator-only sensitivity program linked against the candidate
  objects (mutex serialisation, condition wait/signal, per-thread ids), a
  static-content smoke, and a thread-pool probe that starts a worker and
  serves file content through `aio threads`, including concurrent ranges.
- No separate regression command: the smoke test also covers a plain
  static-serving start.

## Provenance and answer separation

- Windows implementation stays visible: `src/os/win32/ngx_thread.c`,
  `ngx_thread.h`.
- Target implementation is evaluator-only: `src/os/unix/ngx_thread_mutex.c`,
  `ngx_thread_cond.c`, `ngx_thread_id.c` (copied to `gold/` by `prepare.sh`,
  removed from `work/`).
- The Unix header stays visible as the interface contract.