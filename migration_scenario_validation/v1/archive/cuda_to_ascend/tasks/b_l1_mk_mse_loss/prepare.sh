#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"
REPO_DIR="$CACHE/repos/MultiKernelBench-460a972c9be7"
REPO_URL=https://github.com/wzzll123/MultiKernelBench.git
COMMIT=460a972c9be7ce18035984321d38b910e27df95f

mkdir -p "$CACHE/repos"
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone --filter=blob:none --no-checkout "$REPO_URL" "$REPO_DIR"
fi
if ! git -C "$REPO_DIR" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
  git -C "$REPO_DIR" fetch --depth 1 origin "$COMMIT" || true
fi
git -C "$REPO_DIR" checkout --detach "$COMMIT" >/dev/null 2>&1
rm -rf "$ROOT/work"
mkdir -p "$ROOT/work"

git -C "$REPO_DIR" archive "$COMMIT" | tar -x -C "$ROOT/work"

# Copy evaluator-only gold, then remove it from the agent-visible tree.
rm -rf "$ROOT/gold"
mkdir -p "$ROOT/gold"
if [ -e "$ROOT/work"/prompts/ascendc_new_model_mse_loss.py ]; then
  mkdir -p "$ROOT/gold"/"$(dirname prompts/ascendc_new_model_mse_loss.py)"
  cp -a "$ROOT/work"/prompts/ascendc_new_model_mse_loss.py "$ROOT/gold"/prompts/ascendc_new_model_mse_loss.py
fi
rm -rf "$ROOT/work"/prompts/ascendc_new_model_mse_loss.py

if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$ROOT/work/TASK.md"; fi
printf "%s\n" "$COMMIT" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from $REPO_URL@$COMMIT"
