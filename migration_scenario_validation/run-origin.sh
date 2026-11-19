#!/usr/bin/env bash
# Origin baseline: one context packet, one model call, then judge.
#   ./run-origin.sh --scenario ipp_to_vsipl --only l1_aubio_dct
#   ./run-origin.sh --scenario windows_to_kylin --only l1_poco_thread
set -euo pipefail
cd "$(dirname "$0")"
if [ -f bench.env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./bench.env
  set +a
fi
args=("$@")
if [ ${#args[@]} -eq 0 ]; then
  args=(--smoke)
fi
exec python3 tools/bench.py run --arm origin "${args[@]}"
