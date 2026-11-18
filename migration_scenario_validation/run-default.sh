#!/usr/bin/env bash
# One-click entry for condition A: plain DSH, direct migration.
#
#   ./run-default.sh                 # smoke: one task per scenario, 1 run
#   ./run-default.sh --all --runs 3  # full slate
#   ./run-default.sh --dry-run       # show the exact commands, run nothing
#
# Everything else is read from bench.yaml.  Credentials come from bench.env
# (ignored by git), .env at the repository root (../.env), or the inherited
# environment.
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
exec python3 tools/bench.py run --arm default "${args[@]}"