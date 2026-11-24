#!/usr/bin/env bash
# Thread-pool probe for an nginx binary built with --with-threads.
#
# Checks that the server really uses the thread pool backed by the rebuilt
# primitives:
#   1. the worker process owns more than one thread after startup
#   2. static responses served through `aio threads` carry the right body,
#      including several concurrent range requests
#
# Usage: bash nginx_thread_probe.sh --binary /path/to/objs/nginx --port 18084
set -euo pipefail

BINARY=""
PORT=18084
while [ $# -gt 0 ]; do
  case "$1" in
    --binary) BINARY="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$BINARY" ] || [ ! -x "$BINARY" ]; then
  echo "nginx binary not found or not executable: ${BINARY:-<empty>}" >&2
  exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl not available" >&2
  exit 3
fi

TMP="$(mktemp -d)"
MASTER=""
cleanup() {
  if [ -n "$MASTER" ] && kill -0 "$MASTER" 2>/dev/null; then
    kill -QUIT "$MASTER" 2>/dev/null || true
    sleep 0.2
    kill -KILL "$MASTER" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/logs" "$TMP/html"
head -c 262144 /dev/urandom | base64 > "$TMP/html/blob.txt"
PID_FILE="$TMP/logs/nginx.pid"

cat > "$TMP/nginx.conf" <<EOF
worker_processes 1;
error_log $TMP/logs/error.log info;
pid $PID_FILE;
events { worker_connections 64; }
http {
    access_log off;
    client_body_temp_path $TMP/client_body;
    proxy_temp_path $TMP/proxy;
    fastcgi_temp_path $TMP/fastcgi;
    uwsgi_temp_path $TMP/uwsgi;
    scgi_temp_path $TMP/scgi;
    server {
        listen 127.0.0.1:$PORT;
        location / {
            root $TMP/html;
            aio threads;
        }
    }
}
EOF

die() {
  echo "NGINX_THREAD_PROBE=FAIL $*" >&2
  echo "--- error.log ---" >&2
  tail -50 "$TMP/logs/error.log" 2>/dev/null >&2 || true
  exit 1
}

children_of() {
  local ppid="$1"
  local stat pid rest state
  for stat in /proc/[0-9]*/stat; do
    [ -r "$stat" ] || continue
    read -r pid rest < <(sed 's/ (.*) / /' "$stat")
    state="${rest%% *}"
    rest="${rest#* }"
    if [ "${rest%% *}" = "$ppid" ] && [ "$state" != "Z" ]; then
      echo "$pid"
    fi
  done
}

"$BINARY" -p "$TMP/" -c "$TMP/nginx.conf" || die "nginx failed to start (was it built with --with-threads?)"

for _ in $(seq 1 100); do
  [ -s "$PID_FILE" ] && break
  sleep 0.1
done
[ -s "$PID_FILE" ] || die "pid file was not written"
MASTER="$(cat "$PID_FILE")"

WORKER=""
for _ in $(seq 1 100); do
  WORKER="$(children_of "$MASTER" | head -1)"
  [ -n "$WORKER" ] && break
  sleep 0.1
done
[ -n "$WORKER" ] || die "no worker process under master $MASTER"

for _ in $(seq 1 100); do
  [ -d "/proc/$WORKER/task" ] || die "worker $WORKER disappeared"
  NTHREADS="$(ls /proc/$WORKER/task 2>/dev/null | wc -l)"
  [ "$NTHREADS" -gt 1 ] && break
  sleep 0.1
done
[ "${NTHREADS:-0}" -gt 1 ] || die "worker $WORKER has only $NTHREADS thread(s); thread pool not running"
echo "THREADS worker=$WORKER count=$NTHREADS"

EXPECTED="$(wc -c < "$TMP/html/blob.txt")"
for i in $(seq 1 8); do
  BODY_FILE="$TMP/body.$i"
  curl -sf --max-time 10 "http://127.0.0.1:$PORT/blob.txt" -o "$BODY_FILE" \
    || die "request $i through aio threads failed"
  GOT="$(wc -c < "$BODY_FILE")"
  [ "$GOT" -eq "$EXPECTED" ] || die "request $i returned $GOT bytes, expected $EXPECTED"
done

# Concurrent range requests make several threads hit the same file at once.
PIDS=""
for i in $(seq 1 8); do
  ( curl -sf --max-time 10 -r "$((i * 1024))-$((i * 1024 + 4095))" \
      "http://127.0.0.1:$PORT/blob.txt" -o "$TMP/range.$i" ) &
  PIDS="$PIDS $!"
done
for pid in $PIDS; do
  wait "$pid" || die "concurrent range request failed"
done
for i in $(seq 1 8); do
  GOT="$(wc -c < "$TMP/range.$i")"
  [ "$GOT" -eq 4096 ] || die "range request $i returned $GOT bytes, expected 4096"
done

echo "NGINX_THREAD_PROBE=PASS port=$PORT workers=$WORKER threads=$NTHREADS"