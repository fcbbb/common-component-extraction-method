#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED=""
d="$ROOT"
while [ "$d" != "/" ]; do
  if [ -f "$d/shared/harness/tls_probe.sh" ]; then
    SHARED="$d/shared/harness/tls_probe.sh"
    break
  fi
  d="$(dirname "$d")"
done
if [ -z "$SHARED" ]; then
  echo "shared/harness/tls_probe.sh not found above $ROOT" >&2
  exit 2
fi
exec bash "$SHARED" "$@"
