#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

rm -rf "$ROOT/work"
mkdir -p "$ROOT/work"
cp -a "$ROOT/fixture/." "$ROOT/work/"

# The target-platform implementation lives in gold/ only.  The fixture never
# carries it; this is the defence against a stale copied tree.
rm -f "$ROOT/work/src/posix/spl_process_posix.c"
rmdir "$ROOT/work/src/posix" 2>/dev/null || true

printf "synthetic-1\n" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from synthetic://windows-to-posix/event-loop-spawn"