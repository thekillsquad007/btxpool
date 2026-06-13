#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIG="${BTXPOOL_CONFIG:-config.yaml}"

if [[ "$(systemctl is-system-running 2>/dev/null || true)" == "offline" ]]; then
  cat >&2 <<'EOF'
systemd is offline in this WSL distribution.
Enable it in /etc/wsl.conf during a maintenance window, shut WSL down from
Windows, then rerun this installer after the BTX snapshot check passes.
EOF
  exit 1
fi

.venv/bin/python - "$CONFIG" <<'PY'
from pool.btx_rpc import BtxRpcClient
from pool.config import load_config
import sys

cfg = load_config(sys.argv[1])
rpc = BtxRpcClient(
    cfg["rpc_url"],
    cfg.get("rpc_user", ""),
    cfg.get("rpc_password", ""),
    cfg.get("rpc_cookie_file", ""),
)
info = rpc.call("getblockchaininfo", [], timeout=15.0)
snapshot = info.get("snapshot_sync") or {}
if snapshot.get("background_validation_in_progress"):
    raise SystemExit(
        "refusing service installation while snapshot background validation "
        "is in progress"
    )
print("BTX snapshot validation is complete")
PY

sudo install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  btxd.service \
  btxpool.service \
  btxpool-backup.timer \
  btxpool-wallet-backup.timer \
  btxpool-health.timer \
  btxpool-peers.timer

systemctl --no-pager --full status btxd.service btxpool.service
systemctl --no-pager list-timers \
  btxpool-backup.timer \
  btxpool-wallet-backup.timer \
  btxpool-health.timer \
  btxpool-peers.timer
