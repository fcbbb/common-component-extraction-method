#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/work"
rm -rf "$WORK"; mkdir -p "$WORK"
for entry in include test CMakeLists.txt; do
  [ -e "$ROOT/$entry" ] && cp -a "$ROOT/$entry" "$WORK/"
done
printf '%s\n' 'synthetic-windowed-peak-v1' > "$WORK/.source_commit"
printf 'synthetic: windowed-peak-v1\n' > "$WORK/.source_origin"
