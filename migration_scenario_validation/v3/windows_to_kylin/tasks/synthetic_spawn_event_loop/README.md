# synthetic_spawn_event_loop — event-loop process spawn backend

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `C`  **Counted**: no (reported separately)
- **Task family**: `v3` (`synthetic_spawn_event_loop`, `synthetic`)
- **Frozen library**: `v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json`
- **Component exercised**: `process-spawn-backend-for-an-event-loop-win32-handle-c7216288`
- **Source**: `synthetic://windows-to-posix/event-loop-spawn` (project-authored)
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

A portable event-loop runtime keeps its public process surface, its shared
loop and its child probe helper.  Only the platform backend exists for
Windows (`src/win32/spl_process_win32.c`); the POSIX backend
(`src/posix/spl_process_posix.c`) must be written.

The backend owns the stdio descriptor plan, environment and search-path
resolution, session creation, child signal disposition, raw wait-status
decoding and non-blocking reap.  The child-side failures travel back to the
caller through the spawn return value, and a failed spawn leaves a closable,
inactive handle and no zombie.

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
{build}/spl_selftest
```

The hidden probe compiles its checks against `libspl.a` and runs the probe
helper through stdio swaps, ignored slots, environment overrides, detached
sessions, signal deaths, failed spawns, kill semantics and descriptor
hygiene.