# synthetic_thread_runtime — portable threading backend

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `C`  **Counted**: no (reported separately)
- **Task family**: `v3` (`synthetic_thread_runtime`, `synthetic`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component exercised**: `portable-threading-and-synchronisation-backend-for-an-96ad6495`
- **Source**: `synthetic://windows-to-posix/thread-runtime` (project-authored)
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

A portable runtime keeps its public threading surface and its public
self-test.  Only the Windows reference exists (`src/win32/thr_win32.c`); the
POSIX backend (`src/posix/thr_posix.c`) must be written.

The backend owns thread identity and join, the distinction between plain and
recursive mutexes, reader/writer exclusion, semaphore try-wait semantics,
timed condition waits on the monotonic clock, per-thread storage with a
destructor, static one-time initialisation, stack-size requests and the CPU
affinity mask.  All error reporting is translated into the public `THR_*`
codes; the Win32 vocabulary must not survive.

Scope: the platform translation unit only.

## Workspace

```bash
bash prepare.sh
cd work
```

## Build and checks

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release
cmake --build {build} -j2
{build}/thr_selftest
```

The hidden probe compiles its checks against `libthr.a`; it measures join
against `/proc/self/task`, races sixteen threads on one static guard, times a
timed wait on the monotonic clock, measures the actual stack of an
eight-megabyte request under a one-megabyte `ulimit -s`, and applies an
affinity mask taken from the current one.