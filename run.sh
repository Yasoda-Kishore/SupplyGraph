#!/usr/bin/env bash
# Start SupplyGraph on http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
./.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
