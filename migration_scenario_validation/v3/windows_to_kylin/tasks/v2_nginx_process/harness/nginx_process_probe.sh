#!/usr/bin/env bash
# Process-model probe for an nginx binary on Kylin/Linux.
#
# Checks the master/worker lifecycle without relying on procps:
#   1. one master starts and spawns the configured number of workers
#   2. SIGHUP keeps the master and replaces every worker
#   3. SIGQUIT stops master and workers and removes the pid file
#
# Usage: bash nginx_process_probe.sh --binary /path/to/objs/nginx --port 18082
set -euo pipefail

BINARY=""
PORT=18082
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
printf 'process-probe-ok\n' > "$TMP/html/index.html"
PID_FILE="$TMP/logs/nginx.pid"

cat > "$TMP/nginx.conf" <<EOF
worker_processes 2;
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
        location / { root $TMP/html; }
    }
}
EOF

die() {
  echo "NGINX_PROCESS_PROBE=FAIL $*" >&2
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

wait_http() {
  local body
  for _ in $(seq 1 100); do
    if body="$(curl -sf --max-time 1 "http://127.0.0.1:$PORT/")" && [ "$body" = "process-probe-ok" ]; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

# 1. start and count workers
"$BINARY" -p "$TMP/" -c "$TMP/nginx.conf" || die "nginx failed to start"

for _ in $(seq 1 100); do
  [ -s "$PID_FILE" ] && break
  sleep 0.1
done
[ -s "$PID_FILE" ] || die "pid file was not written"
MASTER="$(cat "$PID_FILE")"
kill -0 "$MASTER" 2>/dev/null || die "master $MASTER is not running"

WORKERS_1=""
for _ in $(seq 1 100); do
  WORKERS_1="$(children_of "$MASTER" | sort | tr '\n' ' ')"
  [ "$(echo $WORKERS_1 | wc -w)" -eq 2 ] && break
  sleep 0.1
done
N1="$(echo $WORKERS_1 | wc -w)"
[ "$N1" -eq 2 ] || die "expected 2 workers under master $MASTER, saw $N1 ($WORKERS_1)"
wait_http || die "server did not serve static content before reload"
echo "START master=$MASTER workers=$WORKERS_1"

# 2. reload: master stays, workers are replaced
kill -HUP "$MASTER" || die "SIGHUP could not be delivered"
WORKERS_2=""
for _ in $(seq 1 200); do
  kill -0 "$MASTER" 2>/dev/null || die "master $MASTER exited on reload"
  WORKERS_2="$(children_of "$MASTER" | sort | tr '\n' ' ')"
  if [ "$(echo $WORKERS_2 | wc -w)" -eq 2 ] && [ "$(echo $WORKERS_2)" != "$(echo $WORKERS_1)" ]; then
    break
  fi
  sleep 0.1
done
N2="$(echo $WORKERS_2 | wc -w)"
[ "$N2" -eq 2 ] || die "expected 2 workers after reload, saw $N2 ($WORKERS_2)"
[ "$(echo $WORKERS_2)" != "$(echo $WORKERS_1)" ] || die "reload did not replace workers ($WORKERS_1)"
wait_http || die "server did not serve static content after reload"
echo "RELOAD master=$MASTER workers=$WORKERS_2"

# 3. graceful shutdown: everything exits, pid file disappears
kill -QUIT "$MASTER" || die "SIGQUIT could not be delivered"
for _ in $(seq 1 200); do
  kill -0 "$MASTER" 2>/dev/null || break
  sleep 0.1
done
if kill -0 "$MASTER" 2>/dev/null; then
  die "master $MASTER did not exit on SIGQUIT"
fi
for _ in $(seq 1 100); do
  [ -z "$(children_of "$MASTER")" ] && break
  sleep 0.1
done
REMAIN="$(children_of "$MASTER" | tr '\n' ' ')"
[ -z "$REMAIN" ] || die "workers survived graceful shutdown: $REMAIN"
[ ! -e "$PID_FILE" ] || die "pid file was not removed on graceful shutdown"

echo "NGINX_PROCESS_PROBE=PASS port=$PORT"