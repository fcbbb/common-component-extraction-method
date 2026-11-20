# l3_libgit2_full — libgit2 full POSIX util layer

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`
- **Source**: https://github.com/libgit2/libgit2.git @ `36f7e21ad757a3dacc58cf7944329da6bc1d6e96`
- **License**: GPL-2.0-with-linking-exception
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The complete `src/util/unix/` directory was removed (process, map,
realpath and the pthread/posix wrapper headers).  Rebuild libgit2's
POSIX utility layer so the library compiles and runs on Kylin.  Public libgit2 headers and call sites are unchanged; the
Win32 layer (`src/util/win32/`) stays visible as the reference.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
