# l1_poco_thread — POCO Thread: Win32 threads -> pthreads

- **Scenario**: `windows_to_kylin`
- **Level**: `L1`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

POCO's Foundation library is built from platform-suffixed sources selected
by CMake.  On Kylin the POSIX backend has been removed; the public header
`Poco/Thread.h` and the Win32 implementation `Thread_WIN32.cpp` are still
present as the reference.

Recreate `Foundation/src/Thread_POSIX.cpp` so that Poco::Thread provides
the same contract through the platform thread API: start/join, tryJoin, wakeup after a
timed join, current()/currentTid(), signal handlers, thread priorities,
OS-assigned stack size, and clean TLS teardown.  Keep every public
signature in `Poco/Thread.h` unchanged.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
