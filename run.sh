#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q -r backend/requirements.txt
echo "Starting CloudyAI Model Hub at http://localhost:8000"
uvicorn backend.main:app --port 8000
