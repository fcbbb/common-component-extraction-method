#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"
REPO_DIR="$CACHE/repos/poco-d6bd48a94c5f"
REPO_URL=https://github.com/pocoproject/poco.git
COMMIT=d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b
TAG=poco-1.13.3-release
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
copy_gold Foundation/src/File_UNIX.cpp

# Remove the target-platform implementation from the agent-visible tree.
rm -rf "$ROOT/work"/Foundation/src/File_UNIX.cpp

printf "%s\n" "$COMMIT" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from $REPO_URL@$COMMIT"
