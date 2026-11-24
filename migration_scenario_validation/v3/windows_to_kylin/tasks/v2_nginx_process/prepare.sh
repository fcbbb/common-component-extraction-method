#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"
REPO_DIR="$CACHE/repos/nginx-1be0fb0c9f9b"
REPO_URL=https://github.com/nginx/nginx.git
COMMIT=1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5
TAG=release-1.26.3

mkdir -p "$CACHE/repos"
if [ ! -d "$REPO_DIR/.git" ]; then
  echo "== cloning $REPO_URL =="
  git clone --filter=blob:none --no-checkout "$REPO_URL" "$REPO_DIR"
fi
if ! git -C "$REPO_DIR" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
  echo "== fetching $COMMIT =="
  if ! git -C "$REPO_DIR" fetch --depth 1 origin "$COMMIT"; then
    if [ -n "$TAG" ]; then git -C "$REPO_DIR" fetch --depth 1 origin "refs/tags/$TAG"; fi
  fi
fi
git -C "$REPO_DIR" checkout --detach "$COMMIT" >/dev/null 2>&1

rm -rf "$ROOT/work"
mkdir -p "$ROOT/work"
git -C "$REPO_DIR" archive "$COMMIT" | tar -x -C "$ROOT/work"

# extra test repo: nginx-tests
EXTRA_DIR="$CACHE/repos/nginx-tests-c0b789406302"
if [ ! -d "$EXTRA_DIR/.git" ]; then
  git clone https://github.com/nginx/nginx-tests.git "$EXTRA_DIR"
fi
if ! git -C "$EXTRA_DIR" cat-file -e c0b7894063022fb86d5b5ad732c08507ea03aa78^{commit} 2>/dev/null; then
  git -C "$EXTRA_DIR" fetch --depth 1 origin c0b7894063022fb86d5b5ad732c08507ea03aa78 || true
fi
git -C "$EXTRA_DIR" checkout --detach c0b7894063022fb86d5b5ad732c08507ea03aa78 >/dev/null 2>&1
mkdir -p "$ROOT/work/nginx-tests"
cp -a "$EXTRA_DIR/." "$ROOT/work/nginx-tests/"
rm -rf "$ROOT/work/nginx-tests/.git"

# Target-platform process model implementation -> evaluator-only gold tree.
GOLD_FILES=(
  src/os/unix/ngx_process.c
  src/os/unix/ngx_process_cycle.c
  src/os/unix/ngx_channel.c
  src/os/unix/ngx_daemon.c
)
rm -rf "$ROOT/gold"
mkdir -p "$ROOT/gold"
for rel in "${GOLD_FILES[@]}"; do
  if [ -e "$ROOT/work/$rel" ]; then
    mkdir -p "$ROOT/gold/$(dirname "$rel")"
    cp -a "$ROOT/work/$rel" "$ROOT/gold/$rel"
  fi
done

# Remove them from the agent-visible tree; headers stay as the interface contract.
for rel in "${GOLD_FILES[@]}"; do
  rm -f "$ROOT/work/$rel"
done

printf "%s\n" "$COMMIT" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from $REPO_URL@$COMMIT"