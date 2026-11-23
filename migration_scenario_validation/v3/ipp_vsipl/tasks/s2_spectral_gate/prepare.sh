#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/work"
rm -rf "$WORK"
mkdir -p "$WORK"
for entry in src include test CMakeLists.txt; do
  if [ -e "$ROOT/$entry" ]; then cp -a "$ROOT/$entry" "$WORK/"; fi
done
printf '%s\n' 'synthetic-spectral-gate-v1' > "$WORK/.source_commit"
printf 'synthetic: spectral-gate-v1\n' > "$WORK/.source_origin"
echo "prepared $WORK"