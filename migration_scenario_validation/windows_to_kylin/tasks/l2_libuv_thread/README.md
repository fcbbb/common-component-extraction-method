# l2_libuv_thread — libuv thread layer: Win32 threads -> pthreads

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/libuv/libuv.git @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`
- **License**: MIT
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/unix/thread.c` was removed.  Reimplement libuv's threading layer
with the target thread API: uv_thread_create/join/equal/self, thread names and
affinity/priority, uv_mutex/uv_rwlock/uv_sem/uv_cond/uv_barrier,
uv_once, TLS keys and the thread-pool (uv_queue_work /
uv_cancel).  Preserve the documented return codes and the
EAGAIN-on-exhaustion behaviour.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
