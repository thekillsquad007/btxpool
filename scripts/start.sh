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

RPC_URL="$(
  .venv/bin/python -c \
    'from pool.config import load_config; print(load_config("config.yaml")["rpc_url"])'
)"

case "$RPC_URL" in
  http://127.0.0.1:*|http://localhost:*|http://[::1]:*)
    BTX_DATADIR="${BTX_DATADIR:-$HOME/.bitcoin}"
    BTX_BIN_DIR="${BTX_BIN_DIR:-$HOME/.local/btx/bin}"
    BTXD="${BTXD:-$BTX_BIN_DIR/btxd}"
    BTX_CLI="${BTX_CLI:-$BTX_BIN_DIR/btx-cli}"

    if [[ ! -x "$BTXD" || ! -x "$BTX_CLI" ]]; then
      echo "Local RPC is configured, but btxd/btx-cli were not found in $BTX_BIN_DIR."
      exit 1
    fi

    if ! "$BTX_CLI" -datadir="$BTX_DATADIR" getblockchaininfo >/dev/null 2>&1; then
      if ! pgrep -f "btxd.*-datadir=$BTX_DATADIR" >/dev/null 2>&1; then
        echo "Starting local btxd..."
        "$BTXD" \
          -datadir="$BTX_DATADIR" \
          -addnode=node.btx.tools:19335 \
          -daemon
      fi

      for _ in {1..120}; do
        if "$BTX_CLI" -datadir="$BTX_DATADIR" getblockchaininfo >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done

      if ! "$BTX_CLI" -datadir="$BTX_DATADIR" getblockchaininfo >/dev/null 2>&1; then
        echo "Local btxd RPC did not become ready."
        exit 1
      fi
    fi
    ;;
esac

if [[ ! -d frontend/dist ]]; then
  echo "Building frontend..."
  (cd frontend && npm install && npm run build)
fi

exec .venv/bin/btxpool -c config.yaml
