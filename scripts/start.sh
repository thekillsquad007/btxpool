#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f config.yaml ]]; then
  echo "Create config.yaml from config.example.yaml first."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -e .
fi

if [[ ! -d frontend/dist ]]; then
  echo "Building frontend..."
  (cd frontend && npm install && npm run build)
fi

exec .venv/bin/btxpool -c config.yaml