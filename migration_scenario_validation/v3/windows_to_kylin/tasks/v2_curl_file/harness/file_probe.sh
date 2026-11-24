#!/usr/bin/env bash
# file:// protocol probe.
#
# Exercises the rebuilt FILE handler through the curl tool:
#   1. full-file read to stdout,
#   2. byte range (-r),
#   3. HEAD request with a Content-Length header,
#   4. percent-encoded path containing a space.
#
# Usage:
#   bash file_probe.sh --curl /path/to/curl
set -euo pipefail

CURL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --curl) CURL="$2"; shift 2 ;;
    --path) CURL="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$CURL" ]; then
  echo "no curl binary" >&2
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'hello file\n' > "$TMP/hello.txt"
mkdir -p "$TMP/dir with space"
printf 'spaced content\n' > "$TMP/dir with space/space.txt"
SIZE="$(wc -c < "$TMP/hello.txt")"
SIZE="${SIZE//[[:space:]]/}"

fail() {
  echo "FILE_PROBE=FAIL $*" >&2
  exit 1
}

body="$("$CURL" -sS --max-time 10 "file://$TMP/hello.txt")" || fail "read failed"
[ "$body" = "hello file" ] || fail "unexpected body: $body"

ranged="$("$CURL" -sS --max-time 10 -r 1-3 "file://$TMP/hello.txt")" || fail "range read failed"
[ "$ranged" = "ell" ] || fail "unexpected range body: $ranged"

head="$("$CURL" -sS -I --max-time 10 "file://$TMP/hello.txt")" || fail "HEAD failed"
printf '%s\n' "$head" | grep -qi "^content-length: *$SIZE" \
  || fail "HEAD has no Content-Length: $SIZE"

encoded="$TMP/dir%20with%20space/space.txt"
spaced="$("$CURL" -sS --max-time 10 "file://$encoded")" || fail "percent-decoded read failed"
[ "$spaced" = "spaced content" ] || fail "unexpected percent-decoded body: $spaced"

echo "FILE_PROBE=PASS size=$SIZE"