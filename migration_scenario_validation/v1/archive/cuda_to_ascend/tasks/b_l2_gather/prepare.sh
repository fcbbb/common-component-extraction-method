#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"
REPO_DIR="$CACHE/repos/cann-bench-53ea611a1b88"
REPO_URL=https://gitcode.com/cann/cann-bench.git
COMMIT=53ea611a1b88da922b82812f2721dd0b2fa33476

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

if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$ROOT/work/TASK.md"; fi
printf "%s\n" "$COMMIT" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from $REPO_URL@$COMMIT"
