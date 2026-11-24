#!/usr/bin/env bash
set -euo pipefail
lib="${1:?library path required}"
if nm -g --defined-only "$lib" 2>/dev/null | grep -Eq '(ipps|ippi|ippMalloc|ippFree)'; then
  echo "IPP symbol remains in $lib" >&2
  exit 1
fi
exit 0
