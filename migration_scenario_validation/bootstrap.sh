#!/usr/bin/env bash
# One-command preflight for a fresh checkout.
#
#   ./bootstrap.sh                 # check everything, print what is missing
#   ./bootstrap.sh --fix           # also run npm ci && npm run build in ../dsh
#   ./bootstrap.sh --build-images  # also build the images declared in bench.yaml
#   ./bootstrap.sh --arm method    # method-arm readiness only
#
# It does not download task repositories, model credentials or MUSA materials;
# those requirements are listed in REQUIREMENTS.md and re-checked by doctor.
set -uo pipefail
cd "$(dirname "$0")"

fix=0
images=0
doctor_args=()
for arg in "$@"; do
  case "$arg" in
    --fix) fix=1 ;;
    --build-images) images=1 ;;
    *) doctor_args+=("$arg") ;;
  esac
done

if [ -f bench.env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./bench.env
  set +a
fi

if [ "$fix" = 1 ]; then
  if [ ! -f ../dsh/package.json ]; then
    echo "ERROR ../dsh/package.json not found; run this from inside the repository" >&2
    exit 2
  fi
  node_bin="${COMPONENT_DSH_NODE_BIN:-}"
  if [ -z "$node_bin" ]; then
    node_bin="$(command -v node || true)"
  fi
  if [ -z "$node_bin" ]; then
    echo "ERROR node not found; install Node.js 24.9.0 or set COMPONENT_DSH_NODE_BIN" >&2
    exit 2
  fi
  version="$("$node_bin" -v 2>/dev/null || true)"
  if [ "$version" != "v24.9.0" ]; then
    echo "ERROR node is ${version:-unknown}, expected v24.9.0" >&2
    echo "      install that version, or set COMPONENT_DSH_NODE_BIN to it" >&2
    exit 2
  fi
  npm_bin="$(dirname "$node_bin")/npm"
  if [ ! -x "$npm_bin" ]; then
    npm_bin="$(command -v npm || true)"
  fi
  if [ -z "$npm_bin" ]; then
    echo "ERROR npm not found next to $node_bin" >&2
    exit 2
  fi
  echo "== npm ci =="
  ( cd ../dsh && "$npm_bin" ci ) || { echo "ERROR npm ci failed" >&2; exit 1; }
  echo "== npm run build =="
  ( cd ../dsh && "$npm_bin" run build ) || { echo "ERROR npm run build failed" >&2; exit 1; }
fi

if [ "$images" = 1 ]; then
  echo "== build images =="
  python3 tools/bench.py env
fi

echo "== doctor =="
python3 tools/bench.py doctor ${doctor_args[@]+"${doctor_args[@]}"}
rc=$?

cat <<'EOF'

Python packages (methods, PyYAML, Docker SDK) -- run once, in a venv:
  python3 -m venv .venv && . .venv/bin/activate
  python -m pip install -e ..
  # extras for the full pipeline: pip install -e '..[embeddings,test]'

Prerequisites doctor cannot install (see REQUIREMENTS.md):
  - Docker daemon, and network to Docker Hub / GitHub / npm / PyPI
  - VSIPL_ROOT: a jvsip tree with include/vsip.h and lib/libvsip.a
  - model credentials in ../.env or bench.env
  - MUSA: a real MTT S4000 and env/remote.yaml (copy env/remote.yaml.example)

Without the Docker SDK in the active interpreter the method stages fall back
to the host plane; `doctor` prints that choice and the reason.

Next:
  ./run-default.sh --dry-run
  ./run-default.sh            # smoke: one task per scenario, 1 run
  ./run-method.sh
EOF
exit "$rc"