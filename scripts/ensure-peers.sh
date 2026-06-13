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
MAX_TIP_LAG = 2
MIN_USABLE_PEERS = 3
MIN_NEAR_TIP_PEERS = 3

cfg = load_config(sys.argv[1])
rpc = BtxRpcClient(
    cfg["rpc_url"],
    cfg.get("rpc_user", ""),
    cfg.get("rpc_password", ""),
    cfg.get("rpc_cookie_file", ""),
)
tip = int(rpc.call("getblockcount", [], timeout=15.0))
peers = rpc.call("getpeerinfo", [], timeout=15.0)
usable = [
    peer for peer in peers if int(peer.get("synced_headers") or -1) >= 0
]
near_tip = [
    peer
    for peer in usable
    if int(peer.get("synced_headers") or -1) >= tip - MAX_TIP_LAG
]

if len(usable) >= MIN_USABLE_PEERS and len(near_tip) >= MIN_NEAR_TIP_PEERS:
    print(
        f"BTX peers healthy: {len(usable)} usable, "
        f"{len(near_tip)} near tip {tip}"
    )
    raise SystemExit(0)

connected = {str(peer.get("addr") or "") for peer in peers}
fallbacks = list(OFFICIAL_FALLBACKS)
try:
    addresses = rpc.call("getnodeaddresses", [100], timeout=15.0)
    recent_ipv4 = sorted(
        (
            item
            for item in addresses
            if item.get("network") == "ipv4"
            and int(item.get("port") or 0) > 0
        ),
        key=lambda item: int(item.get("time") or 0),
        reverse=True,
    )
    for item in recent_ipv4:
        address = f"{item['address']}:{int(item['port'])}"
        if address not in connected and address not in fallbacks:
            fallbacks.append(address)
        if len(fallbacks) >= 11:
            break
except Exception as exc:
    print(f"Address database lookup failed: {exc}", file=sys.stderr)

errors = []
for address in fallbacks:
    try:
        rpc.call("addnode", [address, "onetry"], timeout=15.0)
    except Exception as exc:
        errors.append(f"{address}: {exc}")

print(
    f"BTX peers degraded: {len(usable)} usable, {len(near_tip)} within "
    f"{MAX_TIP_LAG} blocks of {tip}; requested fallback connections"
)
if errors:
    print("Fallback connection errors:", "; ".join(errors), file=sys.stderr)
raise SystemExit(1)
PY
