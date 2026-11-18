#!/usr/bin/env bash
# One-click entry for condition B: one main agent, component workflow then migration.
#
#   ./run-method.sh                  # smoke: one task per scenario, 1 run
#   ./run-method.sh --all --runs 3   # full slate
#   ./run-method.sh --dry-run        # show the exact commands, run nothing
#
# Each attempt is one DSH session with the method plugins loaded
# (component-method-migration, method tools only).  The fixed system prompt makes the main agent
# scan the workspace, extract/curate/publish components, run retrieval,
# materialize /workspace/component_bundle, and then complete the same migration
# task in that session.  The main agent has no step limit (budgets.method_* only
# set a wall-clock safety timeout and extraction worker counts); the judged
# artifact is its workspace.
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
exec python3 tools/bench.py run --arm method "${args[@]}"