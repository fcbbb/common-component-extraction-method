#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"
REPO_DIR="$CACHE/repos/curl-7161cb17c01d"
REPO_URL=https://github.com/curl/curl.git
COMMIT=7161cb17c01dcff1dc5bf89a18437d9d729f1ecd
TAG=curl-8_5_0
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

# Gold: the upstream implementation, reduced to the target (POSIX) branch.
# The Win32 branch is dead code on Kylin and would trip the api-removal gate.
rm -rf "$ROOT/gold"
mkdir -p "$ROOT/gold/lib"
cp -a "$ROOT/work/lib/curl_threads.c" "$ROOT/gold/lib/curl_threads.c"
python3 - "$ROOT/gold/lib/curl_threads.c" <<'PY'
import sys

path = sys.argv[1]
out = []
skip = False
depth = 0
with open(path, encoding="utf-8") as fh:
    for line in fh:
        if not skip and line.startswith("#elif defined(USE_THREADS_WIN32)"):
            skip = True
            depth = 0
            continue
        if skip:
            stripped = line.lstrip()
            if stripped.startswith("#if"):
                depth += 1
            elif stripped.startswith("#endif"):
                if depth == 0:
                    out.append("#endif\n")
                    skip = False
                    continue
                depth -= 1
            continue
        out.append(line)
with open(path, "w", encoding="utf-8") as fh:
    fh.write("".join(out))
PY

# Remove the target-platform implementation from the agent-visible tree.
# curl_threads.h (both platform mappings) and the call sites stay visible.
rm -f "$ROOT/work/lib/curl_threads.c"

printf "%s\n" "$COMMIT" > "$ROOT/work/.source_commit"
echo "prepared $ROOT/work from $REPO_URL@$COMMIT"