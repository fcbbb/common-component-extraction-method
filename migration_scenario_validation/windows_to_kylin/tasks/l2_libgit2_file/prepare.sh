#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"
REPO_DIR="$CACHE/repos/libgit2-36f7e21ad757"
REPO_URL=https://github.com/libgit2/libgit2.git
COMMIT=36f7e21ad757a3dacc58cf7944329da6bc1d6e96
TAG=v1.8.1
SUBDIR=''

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
if [ -n "$SUBDIR" ]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  git -C "$REPO_DIR" archive "$COMMIT" "$SUBDIR" | tar -x -C "$TMP"
  cp -a "$TMP/$SUBDIR/." "$ROOT/work/"
else
  git -C "$REPO_DIR" archive "$COMMIT" | tar -x -C "$ROOT/work"
fi

# Copy the target-platform implementation to the evaluator-only gold tree.
rm -rf "$ROOT/gold"
mkdir -p "$ROOT/gold"
copy_gold() {
  rel="$1"
  case "$rel" in
    *[*?[]*)
      mkdir -p "$ROOT/gold/$(dirname "$rel")"
      cp -a $ROOT/work/$rel "$ROOT/gold/$(dirname "$rel")/" 2>/dev/null || true
      ;;
    *)
      if [ -e "$ROOT/work/$rel" ]; then
        mkdir -p "$ROOT/gold/$(dirname "$rel")"
        cp -a "$ROOT/work/$rel" "$ROOT/gold/$rel"
      fi
      ;;
  esac
}
copy_gold src/util/unix/map.c
copy_gold src/util/unix/realpath.c

# Remove the target-platform implementation from the agent-visible tree.
rm -rf "$ROOT/work"/src/util/unix/map.c
rm -rf "$ROOT/work"/src/util/unix/realpath.c

if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$ROOT/work/TASK.md"; fi
printf "%s\n" "$COMMIT" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from $REPO_URL@$COMMIT"
