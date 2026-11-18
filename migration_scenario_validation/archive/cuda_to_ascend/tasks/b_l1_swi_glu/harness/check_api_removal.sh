#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED=""
d="$ROOT"
while [ "$d" != "/" ]; do
  if [ -f "$d/shared/harness/api_removal.py" ]; then
    SHARED="$d/shared/harness/api_removal.py"
    break
  fi
  d="$(dirname "$d")"
done
if [ -z "$SHARED" ]; then
  echo "shared/harness/api_removal.py not found above $ROOT" >&2
  exit 2
fi
exec python3 "$SHARED" --source-dir "$ROOT/work/submission" --symbol-regex '' --source-regex '__global__|__shared__|threadIdx|blockIdx|<<<|cuda[A-Z]\w*\(|#include\s*[<"]cuda|nvcc' "$@"
