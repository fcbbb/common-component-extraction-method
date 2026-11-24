#!/usr/bin/env bash
# Hidden probe for the synthetic multi-call-site task.
#
# Runs every application that shares the platform-layer convention and the
# public platform checks, from a scratch directory, using Windows-style
# backslash paths.
#
# Usage:
#   bash mc_probe.sh --build /path/to/build
set -euo pipefail

BUILD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$BUILD" ]; then
  echo "no build directory" >&2
  exit 2
fi

for tool in mcdump mccount mccopy mctail test_platform; do
  if [ ! -x "$BUILD/$tool" ]; then
    echo "MC_PROBE=FAIL missing $BUILD/$tool" >&2
    exit 1
  fi
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/data" "$TMP/out"
printf 'alpha\nbeta\ngamma\n' > "$TMP/data/sample.txt"
: > "$TMP/data/empty.txt"
SIZE="$(wc -c < "$TMP/data/sample.txt")"
SIZE="${SIZE//[[:space:]]/}"

fail() {
  echo "MC_PROBE=FAIL $*" >&2
  exit 1
}

# The target image has no diffutils, so compare content digests instead of
# relying on cmp(1).
same_bytes() {
  local a b
  a="$(md5sum < "$1" | cut -d' ' -f1)"
  b="$(md5sum < "$2" | cut -d' ' -f1)"
  [ "$a" = "$b" ]
}

cd "$TMP"

"$BUILD/mcdump" 'data\sample.txt' > dump.out || fail "mcdump exited non-zero"
same_bytes dump.out data/sample.txt || fail "mcdump output differs"

count="$("$BUILD/mccount" 'data\sample.txt')" || fail "mccount exited non-zero"
[ "$count" = "$SIZE" ] || fail "mccount $count != $SIZE"

"$BUILD/mccopy" 'data\sample.txt' 'out\copy.txt' || fail "mccopy exited non-zero"
same_bytes out/copy.txt data/sample.txt || fail "mccopy output differs"

tail_out="$("$BUILD/mctail" 'data\sample.txt' 5)" || fail "mctail exited non-zero"
[ "$tail_out" = "amma" ] || fail "mctail returned '$tail_out'"

"$BUILD/mcdump" 'data\empty.txt' > empty.out || fail "mcdump empty exited non-zero"
[ ! -s empty.out ] || fail "mcdump empty produced output"
count="$("$BUILD/mccount" 'data\empty.txt')" || fail "mccount empty exited non-zero"
[ "$count" = "0" ] || fail "empty size $count != 0"
"$BUILD/mccopy" 'data\empty.txt' 'out\empty.txt' || fail "mccopy empty exited non-zero"
[ ! -s out/empty.txt ] || fail "mccopy empty produced output"

mkdir -p sub
"$BUILD/test_platform" > test.out 2>&1 || { cat test.out >&2; fail "test_platform exited non-zero"; }

echo "MC_PROBE=PASS size=$SIZE"