#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED=""
d="$ROOT"
while [ "$d" != "/" ]; do
  if [ -f "$d/shared/harness/nginx_smoke.sh" ]; then
    SHARED="$d/shared/harness/nginx_smoke.sh"
    break
  fi
  d="$(dirname "$d")"
done
if [ -z "$SHARED" ]; then
  echo "shared/harness/nginx_smoke.sh not found above $ROOT" >&2
  exit 2
fi
exec bash "$SHARED" "$@"
