#!/usr/bin/env bash
# Hidden probe for the process-spawn backend.
#
# Usage:
#   bash spl_probe.sh --build /path/to/build --work /path/to/work
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD=""
WORK=""

while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$BUILD" ] || [ -z "$WORK" ]; then
  echo "usage: spl_probe.sh --build <build> --work <work>" >&2
  exit 2
fi

fail() {
  echo "SPL_PROBE=FAIL $*" >&2
  exit 1
}

[ -x "$BUILD/spl_selftest" ] || fail "missing $BUILD/spl_selftest"
[ -x "$BUILD/splprobe" ] || fail "missing $BUILD/splprobe"
[ -f "$BUILD/libspl.a" ] || fail "missing $BUILD/libspl.a"

CC="${CC:-cc}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scratch"

"$BUILD/spl_selftest" > "$TMP/selftest.log" 2>&1 || {
  cat "$TMP/selftest.log" >&2
  fail "public self-test"
}

"$CC" -std=gnu99 -D_GNU_SOURCE -O2 -I "$WORK/include" -I "$WORK/src/common" \
  "$ROOT/harness/deep_spawn.c" -o "$TMP/deep_spawn" \
  -L "$BUILD" -lspl > "$TMP/compile.log" 2>&1 || {
  cat "$TMP/compile.log" >&2
  fail "cannot compile the hidden probe"
}

"$TMP/deep_spawn" "$TMP/scratch" "$BUILD/splprobe" || \
  fail "process-contract checks"

echo "SPL_PROBE=PASS"