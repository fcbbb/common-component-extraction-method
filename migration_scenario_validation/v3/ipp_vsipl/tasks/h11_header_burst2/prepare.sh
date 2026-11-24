#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/work"
rm -rf "$WORK"
mkdir -p "$WORK"
for entry in include src test CMakeLists.txt; do
  if [ -e "$ROOT/$entry" ]; then cp -a "$ROOT/$entry" "$WORK/"; fi
done
printf '%s\n' 'synthetic-header-burst2-v1' > "$WORK/.source_commit"
printf 'synthetic: burst-header-only-v1\n' > "$WORK/.source_origin"
echo "prepared $WORK"