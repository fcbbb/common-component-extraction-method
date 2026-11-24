#!/usr/bin/env bash
# Threaded-resolver probe.
#
# Checks that the rebuilt thread backend is actually wired into curl:
#   1. the binary reports the AsynchDNS feature (USE_THREADS_POSIX path),
#   2. name resolution runs through the resolver thread and a real request to
#      http://localhost:<port>/ succeeds.
#
# Usage:
#   bash thread_probe.sh --port 18086 --curl /path/to/curl
set -euo pipefail

PORT=18086
CURL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
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
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

if ! "$CURL" --version | grep -q 'AsynchDNS'; then
  echo "THREAD_PROBE=FAIL no AsynchDNS in --version" >&2
  "$CURL" --version >&2 || true
  exit 1
fi

mkdir -p "$TMP/www"
printf 'thread-resolver-ok\n' > "$TMP/www/index.html"
(
  cd "$TMP/www"
  exec python3 -m http.server "$PORT" --bind 127.0.0.1
) >"$TMP/server.log" 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 50); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    break
  fi
  if "$CURL" -sS --max-time 2 "http://127.0.0.1:$PORT/index.html" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.2
done
if [ "$ready" != 1 ]; then
  echo "THREAD_PROBE=FAIL local server did not come up" >&2
  cat "$TMP/server.log" >&2 || true
  exit 1
fi

if ! out="$("$CURL" -sS --max-time 10 "http://localhost:$PORT/index.html" 2>"$TMP/client.err")"; then
  echo "THREAD_PROBE=FAIL request through hostname resolver failed" >&2
  cat "$TMP/client.err" >&2 || true
  exit 1
fi
if [ "$out" != "thread-resolver-ok" ]; then
  echo "THREAD_PROBE=FAIL unexpected body: $out" >&2
  exit 1
fi

echo "THREAD_PROBE=PASS port=$PORT"