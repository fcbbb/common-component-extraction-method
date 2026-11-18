#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED=""
d="$ROOT"
while [ "$d" != "/" ]; do
  if [ -f "$d/shared/harness/api_removal.py" ]; then
    SHARED="$d/shared/harness/api_removal.py"
    break
  fi
  d="$(dirname "$d")"
done
if [ -z "$SHARED" ]; then
  echo "shared/harness/api_removal.py not found above $ROOT" >&2
  exit 2
fi
exec python3 "$SHARED" \
  --source-dir "$ROOT/work/Foundation/src/EventLogChannel.cpp" \
  --expect-fail --symbol-regex '^(ReportEvent|RegisterEventSource|DeregisterEventSource|OpenEventLog)' \
  --source-regex 'windows\.h|ReportEvent|RegisterEventSource|HKEY_|RegCreateKey|pocomsg' \
  "$@"
