#!/usr/bin/env bash
# Run CloudyAI Model Hub locally at http://localhost:8000.
#
#   ./run.sh             use the live Hugging Face Hub (set HF_TOKEN for gated models)
#   ./run.sh --offline   use the bundled fixtures instead of the network
#
# Dependencies are read from pyproject.toml. The first run creates .venv in the repository.
set -euo pipefail
cd "$(dirname "$0")"

offline=0
case "${1:-}" in
  "") ;;
  --offline) offline=1 ;;
  -h | --help)
    sed -n '2,6p' "$0"
    exit 0
    ;;
  *)
    echo "Unknown option: $1 (try --offline or --help)" >&2
    exit 2
    ;;
esac

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet -e ".[dev]"

if [ "$offline" -eq 1 ]; then
  python scripts/mock_hub.py --port 8787 &
  mock_pid=$!
  trap 'kill "$mock_pid" 2>/dev/null || true' EXIT
  export HF_ENDPOINT="http://127.0.0.1:8787"
  echo "Offline mode: bundled fixtures served from http://127.0.0.1:8787"
fi

echo "CloudyAI Model Hub: http://localhost:8000 (listens on this machine only; API docs at /api/docs)"
uvicorn backend.main:app --port 8000
