# l1_poco_rwlock_semaphore — POCO RWLock + Semaphore: Win32 primitives -> pthread primitives

- **Scenario**: `windows_to_kylin`
- **Level**: `L1`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Recreate both POSIX backends.  RWLock must support read/write lock,
tryReadLock/tryWriteLock, unlock and the timeout variants; Semaphore must
support wait, tryWait, wait(timeout) and set, with EINTR retry loops.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
