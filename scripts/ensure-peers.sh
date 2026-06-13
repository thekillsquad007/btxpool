#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIG="${BTXPOOL_CONFIG:-config.yaml}"

.venv/bin/python - "$CONFIG" <<'PY'
from __future__ import annotations

import sys

from pool.btx_rpc import BtxRpcClient
from pool.config import load_config

OFFICIAL_FALLBACKS = (
    "node.btx.tools:19335",
    "146.190.179.86:19335",
    "164.90.246.229:19335",
)
MAX_TIP_LAG = 6

cfg = load_config(sys.argv[1])
rpc = BtxRpcClient(
    cfg["rpc_url"],
    cfg.get("rpc_user", ""),
    cfg.get("rpc_password", ""),
    cfg.get("rpc_cookie_file", ""),
)
tip = int(rpc.call("getblockcount", [], timeout=15.0))
peers = rpc.call("getpeerinfo", [], timeout=15.0)
near_tip = [
    peer
    for peer in peers
    if int(peer.get("synced_headers") or -1) >= tip - MAX_TIP_LAG
]

if near_tip:
    print(f"BTX peers healthy: {len(near_tip)} near tip {tip}")
    raise SystemExit(0)

errors = []
for address in OFFICIAL_FALLBACKS:
    try:
        rpc.call("addnode", [address, "onetry"], timeout=15.0)
    except Exception as exc:
        errors.append(f"{address}: {exc}")

print(
    f"BTX peers degraded: no peer within {MAX_TIP_LAG} blocks of {tip}; "
    "requested official fallback connections"
)
if errors:
    print("Fallback connection errors:", "; ".join(errors), file=sys.stderr)
raise SystemExit(1)
PY
