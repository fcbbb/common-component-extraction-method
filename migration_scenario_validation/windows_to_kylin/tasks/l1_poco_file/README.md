# l1_poco_file — POCO File: Win32 file handles -> POSIX file descriptors

- **Scenario**: `windows_to_kylin`
- **Level**: `L1`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Recreate `Foundation/src/File_UNIX.cpp`.  Keep the same Poco::File observable behaviour:
  - exists(), isFile(), isDirectory(), isLink(), canRead/canWrite
  - sizes, timestamps, permissions (mode bits mapping)
  - copyTo/moveTo across directories, symbolic and hard links
  - directory iteration and the usual ENOENT/EEXIST error mapping

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
