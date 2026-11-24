# synthetic_multi_call_site — multi-call-site convention migration

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `C`  **Counted**: no (reported separately)
- **Task family**: `v3` (`synthetic_multi_call_site`, `synthetic`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Components exercised**: file-system ×2 + process/threading conventions (T1/T2/T4/T5)
- **Source**: `synthetic://windows-to-posix/multi-call-site` (project-authored)
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Four command-line tools share one minimal I/O layer.  The tools were
written on Windows and rely on a convention that is never stated in one
place:

- an integer handle with `-1` as the invalid sentinel,
- `\` as the path separator,
- `read`/`write` returning a byte count, `0` at end of file and `-1` on
  error,
- `seek` returning the new absolute offset,
- `size` returning the byte size,
- `close` returning `0`/`-1`.

The Windows implementation (`src/win32/mc_platform_win32.c`) stays
visible as the reference.  Implement `src/posix/mc_platform_posix.c` so
all four tools and the public platform checks keep the convention on
Kylin.

Scope: the platform translation unit only.  Do not change the header,
the call sites or the Win32 reference.

## Workspace

```bash
bash prepare.sh
cd work
```

## Build and checks

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release
cmake --build {build} -j2
cd {build} && ./test_platform
```

The hidden probe (`harness/mc_probe.sh`) runs `mcdump`, `mccount`,
`mccopy` and `mctail` from a scratch directory with backslash paths,
including empty files, and then runs `test_platform`.