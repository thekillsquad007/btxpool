#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BTX_DATADIR="${BTX_DATADIR:-$HOME/.bitcoin}"
BTX_BIN_DIR="${BTX_BIN_DIR:-$HOME/.local/btx/bin}"
STATE_DIR="${BTXPOOL_STATE_DIR:-$HOME/.local/share/btxpool}"
mkdir -p "$STATE_DIR"

if ! "$BTX_BIN_DIR/btx-cli" \
  -datadir="$BTX_DATADIR" \
  -conf="$BTX_DATADIR/btx.conf" \
  getblockchaininfo >/dev/null 2>&1; then
  "$BTX_BIN_DIR/btxd" -datadir="$BTX_DATADIR" -daemon
  for _ in {1..120}; do
    "$BTX_BIN_DIR/btx-cli" \
      -datadir="$BTX_DATADIR" \
      -conf="$BTX_DATADIR/btx.conf" \
      getblockchaininfo >/dev/null 2>&1 && break
    sleep 1
  done
fi

if ! pgrep -f "$ROOT/.venv/bin/.*btxpool -c config.yaml" >/dev/null 2>&1; then
  nohup "$ROOT/.venv/bin/btxpool" -c config.yaml \
    >>"$STATE_DIR/pool-supervised.log" 2>&1 </dev/null &
fi

for _ in {1..30}; do
  curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1 && exit 0
  sleep 1
done

echo "BTX pool API did not become reachable" >&2
exit 1
