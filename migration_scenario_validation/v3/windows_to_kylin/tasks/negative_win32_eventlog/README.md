# negative_win32_eventlog — Negative control: Windows Event Log channel has no equivalent

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`  **Fit**: `C`
- **Task family**: `v3` (`poco_foundation`, `negative_control`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Poco::EventLogChannel is being assessed for a move from Windows
to Kylin V10 SP3.  Windows Event Log reporting has no direct
equivalent on the target platform.

The channel writes records through the Windows Event Log API,
registers an event source in the registry and loads message-table
resources compiled from Windows resource files.  Kylin has no
Event Log service, no equivalent event-source registration and no
message-table resource compiler.

Scope: this task does not port the component.  Write
`work/PORTING_NOTES.md` that names the platform-only APIs and
their call sites, explains why a system-log service is not a
behaviour-preserving replacement, and states what a product team
would have to redesign.  Deliverable: the report; do not add a
stub backend.

Target environment: Kylin V10 SP3, x86_64, GCC 13.3, CMake
3.16.5.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The Windows implementation and the public headers stay visible as the
reference.  The deliverable is `work/PORTING_NOTES.md`; do not add a stub
backend.

## Build

Not applicable: the module cannot be built on the target platform.
