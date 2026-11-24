#!/usr/bin/env bash
# Hidden probe for the threading backend.
#
# Usage:
#   bash thr_probe.sh --build /path/to/build --work /path/to/work
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
  echo "usage: thr_probe.sh --build <build> --work <work>" >&2
  exit 2
fi

fail() {
  echo "THR_PROBE=FAIL $*" >&2
  exit 1
}

[ -x "$BUILD/thr_selftest" ] || fail "missing $BUILD/thr_selftest"
[ -f "$BUILD/libthr.a" ] || fail "missing $BUILD/libthr.a"

CC="${CC:-cc}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

"$BUILD/thr_selftest" > "$TMP/selftest.log" 2>&1 || {
  cat "$TMP/selftest.log" >&2
  fail "public self-test"
}

"$CC" -std=gnu99 -D_GNU_SOURCE -O2 -I "$WORK/include" \
  "$ROOT/harness/deep_thr.c" -o "$TMP/deep_thr" \
  -L "$BUILD" -lthr -pthread > "$TMP/compile.log" 2>&1 || {
  cat "$TMP/compile.log" >&2
  fail "cannot compile the hidden probe"
}

# The default thread stack is initialised from RLIMIT_STACK at start-up, so
# lower it before the process starts: an implementation that ignores the
# explicit stack request cannot then hide behind a large default.
( ulimit -s 1024 2>/dev/null || true
  "$TMP/deep_thr" ) || fail "threading-contract checks"

echo "THR_PROBE=PASS"