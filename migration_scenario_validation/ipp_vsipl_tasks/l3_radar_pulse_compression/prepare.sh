#!/usr/bin/env bash
# Vendored snapshot: no network access is required or performed.
# The IPP source state is already in this package under src/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/work"
REPO='synthetic (radar pulse-compression frontend)'
COMMIT='-'

rm -rf "$WORK"
mkdir -p "$WORK"
for entry in src include test CMakeLists.txt support; do
  if [ -e "$ROOT/$entry" ]; then
    cp -a "$ROOT/$entry" "$WORK/"
  fi
done

printf '%s\n' "$COMMIT" > "$WORK/.source_commit"
printf 'vendored: %s @ %s\n' "$REPO" "$COMMIT" > "$WORK/.source_origin"
echo "prepared $WORK (vendored $REPO@$COMMIT)"