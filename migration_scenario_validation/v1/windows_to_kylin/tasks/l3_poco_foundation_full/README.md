# l3_poco_foundation_full — POCO Foundation full POSIX platform layer

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

All POSIX/UNIX implementations under `Foundation/src/` were removed in
one go (17 files).  Rebuild the whole Foundation platform layer for
Kylin: threads, mutexes, events, rwlocks, semaphores, files, paths,
streams, processes, pipes, shared memory/libraries, environment,
directory iteration and timezone.  This is the calibration point for
"one repository, many coupled backends"; partial ports will not link.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
