#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; WORK="$ROOT/work"; rm -rf "$WORK"; mkdir -p "$WORK"
for e in src include test CMakeLists.txt; do [ -e "$ROOT/$e" ] && cp -a "$ROOT/$e" "$WORK/"; done
printf '%s\n' synthetic-norm-corr-v1 > "$WORK/.source_commit"; printf 'synthetic: norm-corr-v1\n' > "$WORK/.source_origin"
