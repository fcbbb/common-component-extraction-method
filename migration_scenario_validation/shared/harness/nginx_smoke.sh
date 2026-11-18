#!/usr/bin/env bash
# Static-file smoke test for an nginx binary on Kylin/Linux.
#
# Usage:
#   bash nginx_smoke.sh --binary /path/to/objs/nginx --port 18080
set -euo pipefail

BINARY=""
PORT=18080
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
PID=""
cleanup() {
  if [ -n "$PID" ]; then
    "$BINARY" -p "$TMP/" -c "$TMP/nginx.conf" -s quit >/dev/null 2>&1 || true
    kill "$PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/logs" "$TMP/html"
printf 'kylin-nginx-ok\n' > "$TMP/html/index.html"

cat > "$TMP/nginx.conf" <<EOF
daemon off;
worker_processes 1;
error_log $TMP/logs/error.log info;
pid $TMP/logs/nginx.pid;
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
        location / { root $TMP/html; }
    }
}
EOF

"$BINARY" -p "$TMP/" -c "$TMP/nginx.conf" >"$TMP/nginx.out" 2>&1 &
PID=$!

for _ in $(seq 1 50); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "nginx exited early:" >&2
    cat "$TMP/logs/error.log" "$TMP/nginx.out" 2>/dev/null >&2 || true
    exit 1
  fi
  if body="$(curl -sf --max-time 2 "http://127.0.0.1:$PORT/")" && [ "$body" = "kylin-nginx-ok" ]; then
    echo "NGINX_SMOKE=PASS port=$PORT body=$body"
    exit 0
  fi
  sleep 0.2
done

echo "NGINX_SMOKE=FAIL port=$PORT" >&2
cat "$TMP/logs/error.log" "$TMP/nginx.out" 2>/dev/null >&2 || true
exit 1