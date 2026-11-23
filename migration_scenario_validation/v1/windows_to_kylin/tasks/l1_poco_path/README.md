# l1_poco_path — POCO Path: Win32 path rules -> POSIX path rules

- **Scenario**: `windows_to_kylin`
- **Level**: `L1`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Recreate `Foundation/src/Path_UNIX.cpp`.  Path semantics are the trap:
separators are '/', drive letters and UNC prefixes disappear, '~' is
expanded from $HOME, case sensitivity changes, and the Windows
MAX_PATH-based buffer logic must become dynamic.  Keep the Poco::Path API
(parse, makeAbsolute, makeRelative, resolve, current, home, temp, list)
and the expected error behaviour for malformed input.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
