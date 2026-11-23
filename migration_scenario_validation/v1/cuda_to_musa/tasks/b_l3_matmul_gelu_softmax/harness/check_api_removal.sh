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
exec python3 "$SHARED" --source-dir "$ROOT/work/submission" --symbol-regex '' --source-regex 'torch\.cuda|\.cuda\(\)|cuda[A-Z]\w*\s*\(|#include\s*[<"]cuda|#include\s*[<"]cublas|#include\s*[<"]cudnn|#include\s*[<"]cufft|\bnvcc\b|\bcublas[A-Za-z0-9_]*\s*\(|\bcudnn[A-Za-z0-9_]*\s*\(|\bcufft[A-Za-z0-9_]*\s*\(|device\s*=\s*['"'"'"]cuda|\bCUDA_[A-Z0-9_]+|__CUDACC__' "$@"
