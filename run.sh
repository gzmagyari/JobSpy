#!/bin/bash
# Launch the Job Matcher dashboard (backend + built frontend) on http://localhost:8077
# Usage (from WSL):  bash run.sh
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

if [ ! -x .venv/bin/python ]; then
  echo "ERROR: .venv not found. Create it first:"
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -e . -r requirements-app.txt"
  exit 1
fi

# Build the Vue frontend on first run (or after deleting app/frontend/dist).
if [ ! -d app/frontend/dist ]; then
  echo "Frontend not built yet — building…"
  export NVM_DIR="$HOME/.nvm"
  # shellcheck disable=SC1090
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  ( cd app/frontend && npm install --no-audit --no-fund && npm run build )
fi

export PYTHONPATH="$ROOT"
# Bind 0.0.0.0 (not 127.0.0.1) so Windows can reach it reliably even when WSL2's
# localhost-forwarding bridge drops — fall back to http://<wsl-ip>:8077 if needed.
echo "Starting on http://localhost:8077  (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8077
