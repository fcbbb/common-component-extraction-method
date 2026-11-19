# negative_win32_eventlog — Negative control: Windows Event Log channel has no equivalent

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`Poco::EventLogChannel` writes to the Windows Event Log through
ReportEvent, registers an event source in the registry and loads
message-table resources compiled from `pocomsg.mc`.  Kylin has no
Event Log service, no equivalent registry event-source registration and
no message-table resource compiler.

The correct outcome is an explicit non-portability report, not a stub
that silently drops log records.  Write `work/PORTING_NOTES.md` that:
  - names the platform-only APIs and where they are used;
  - explains why syslog/journald is not a behaviour-preserving
    replacement (different record model, source registration, IDs);
  - states what a product team would have to redesign.
The API-removal gate is expected to FAIL on this task; it is a control
for "the agent fabricated a port".

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
