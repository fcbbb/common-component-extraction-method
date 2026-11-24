# v2_nginx_process — Migrate the nginx process layer to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`nginx_os`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component used**: `process-spawn-backend-for-an-event-loop-win32-handle-c7216288` (process)
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5` (release-1.26.3)
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

nginx is being moved from Windows to Kylin V10 SP3.  The target-platform
process model has not been written yet.

Rebuild the master/worker process layer: worker spawning, the master/worker
channel socket pair, command delivery and acknowledgement, signal handling,
the process-cycle state machine (spawn, reload, graceful shutdown, reopen
logs) and daemonisation.  The module headers, the server core, the Win32
implementation and the configure entry stay visible as the reference.

Scope: the process layer only; do not change module interfaces or build
configuration.  Deliverable: `objs/nginx`, built by the repository configure
entry.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The four Unix process files are removed; `src/os/win32/ngx_process*.c` and the
Unix headers remain visible.  `nginx-tests` is materialized under `work/`.

## Build

```bash
./auto/configure --prefix={build}/nginx --without-http_rewrite_module --without-http_gzip_module && make -j
```

## Tests

- Hidden: static-content smoke, a master/worker lifecycle probe (2 workers,
  SIGHUP reload replaces workers, SIGQUIT removes master/workers/pid file),
  and upstream `worker_channel.t` + `worker_shutdown_timeout.t`.
- No separate regression command: the smoke test runs first and covers
  startup and static serving.

## Provenance and answer separation

- Windows implementation stays visible: `src/os/win32/ngx_process.c`,
  `ngx_process_cycle.c`.
- Target implementation is evaluator-only: `src/os/unix/ngx_process.c`,
  `ngx_process_cycle.c`, `ngx_channel.c`, `ngx_daemon.c` (copied to `gold/` by
  `prepare.sh`, removed from `work/`).
- Unix headers stay visible as the interface contract.