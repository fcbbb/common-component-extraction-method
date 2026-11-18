#!/usr/bin/env bash
# TLS smoke probe shared by the Windows->Kylin and CUDA->Ascend scenarios.
#
# Starts a local `openssl s_server` and runs a client command against it.  The
# client command is passed as a single string and is expected to exit 0.
#
# Usage:
#   bash tls_probe.sh --client "curl -sk --max-time 10 https://127.0.0.1:18443/"
#   bash tls_probe.sh --path /path/to/curl --port 18444
set -euo pipefail

PORT=18443
CLIENT=""
PATH_HINT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --client) CLIENT="$2"; shift 2 ;;
    --path) PATH_HINT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -n "$PATH_HINT" ] && [ -z "$CLIENT" ]; then
  CLIENT="$PATH_HINT -sk --max-time 10 https://127.0.0.1:$PORT/"
fi
if [ -z "$CLIENT" ]; then
  echo "no client command" >&2
  exit 2
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl not available; cannot run TLS probe" >&2
  exit 3
fi

TMP="$(mktemp -d)"
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$TMP/key.pem" -out "$TMP/cert.pem" -days 1 -subj "/CN=localhost" \
  >/dev/null 2>&1

openssl s_server -www -quiet -accept "$PORT" \
  -cert "$TMP/cert.pem" -key "$TMP/key.pem" >"$TMP/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "s_server exited early:" >&2
    cat "$TMP/server.log" >&2 || true
    exit 1
  fi
  if bash -c "$CLIENT" >/dev/null 2>&1; then
    echo "TLS_PROBE=PASS port=$PORT client=$CLIENT"
    exit 0
  fi
  sleep 0.2
done

echo "TLS_PROBE=FAIL port=$PORT client=$CLIENT" >&2
cat "$TMP/server.log" >&2 || true
exit 1