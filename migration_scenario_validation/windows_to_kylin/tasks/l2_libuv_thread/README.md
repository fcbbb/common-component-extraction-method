# l2_libuv_thread — libuv thread layer: Win32 threads -> pthreads

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/libuv/libuv.git @ `e9f29cb984231524e3931aa0ae2c5dae1a32884e`
- **License**: MIT
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/unix/thread.c` was removed.  Reimplement libuv's threading layer
with pthreads: uv_thread_create/join/equal/self, thread names and
affinity/priority, uv_mutex/uv_rwlock/uv_sem/uv_cond/uv_barrier,
uv_once, TLS keys and the thread-pool (uv_queue_work /
uv_cancel).  Preserve the documented return codes and the
EAGAIN-on-exhaustion behaviour.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLIBUV_BUILD_SHARED=ON && cmake --build {build} -j
```

## Hidden tests

```bash
cd {work} && {build}/uv_run_tests_a thread_create && {build}/uv_run_tests_a thread_equal && {build}/uv_run_tests_a thread_affinity && {build}/uv_run_tests_a thread_priority && {build}/uv_run_tests_a thread_mutex && {build}/uv_run_tests_a thread_rwlock && {build}/uv_run_tests_a thread_local_storage && {build}/uv_run_tests_a barrier_serial_thread && {build}/uv_run_tests_a condvar_1 && {build}/uv_run_tests_a semaphore_1 && {build}/uv_run_tests_a threadpool_queue_work_simple && {build}/uv_run_tests_a threadpool_cancel_single
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
