#!/usr/bin/env bash
# Hidden probe for the asynchronous file-system request task.
#
# Builds the hidden checks against the produced static library, runs the
# public self-test and the request-contract checks, and verifies that the
# descriptors the library opens are close-on-exec.
#
# Usage:
#   bash afs_probe.sh --build /path/to/build --work /path/to/work
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
  echo "usage: afs_probe.sh --build <build> --work <work>" >&2
  exit 2
fi

fail() {
  echo "AFS_PROBE=FAIL $*" >&2
  exit 1
}

[ -x "$BUILD/afs_selftest" ] || fail "missing $BUILD/afs_selftest"
[ -f "$BUILD/libafs.a" ] || fail "missing $BUILD/libafs.a"

CC="${CC:-cc}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scratch"

"$BUILD/afs_selftest" "$TMP/scratch" > "$TMP/selftest.log" 2>&1 || {
  cat "$TMP/selftest.log" >&2
  fail "public self-test"
}

"$CC" -std=gnu99 -D_GNU_SOURCE -O2 -I "$WORK/include" -I "$WORK/src/common" \
  "$ROOT/harness/deep_probe.c" -o "$TMP/deep_probe" \
  -L "$BUILD" -lafs -lpthread > "$TMP/compile.log" 2>&1 || {
  cat "$TMP/compile.log" >&2
  fail "cannot compile the hidden probe"
}

"$TMP/deep_probe" "$TMP/deep" || fail "request-contract checks"

"$CC" -std=gnu99 -D_GNU_SOURCE -O2 -I "$WORK/include" \
  "$ROOT/harness/fd_inherit.c" -o "$TMP/fd_inherit" \
  -L "$BUILD" -lafs -lpthread > "$TMP/compile_fd.log" 2>&1 || {
  cat "$TMP/compile_fd.log" >&2
  fail "cannot compile the descriptor check"
}

printf 'descriptor fixture\n' > "$TMP/scratch/fd_fixture.txt"
listing="$("$TMP/fd_inherit" "$TMP/scratch/fd_fixture.txt" "$TMP/fds.txt")" || \
  fail "descriptor check"
printf '%s\n' "$listing"
fd="$(printf '%s\n' "$listing" | sed -n 's/^OPENFD=//p')"
[ -n "$fd" ] || fail "descriptor check printed no descriptor"
if grep -qx "$fd" "$TMP/fds.txt"; then
  cat "$TMP/fds.txt" >&2
  fail "descriptor $fd opened by the library leaked into a child process"
fi

echo "AFS_PROBE=PASS"