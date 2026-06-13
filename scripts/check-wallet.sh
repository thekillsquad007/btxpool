#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

.venv/bin/python <<'PY'
from pool.btx_rpc import BtxRpcClient
from pool.config import load_config

cfg = load_config("config.yaml")
wallet_name = cfg.get("rpc_wallet", "")
if not wallet_name:
    raise SystemExit("rpc_wallet is not configured")

rpc = BtxRpcClient(
    cfg["rpc_url"],
    cfg.get("rpc_user", ""),
    cfg.get("rpc_password", ""),
    cfg.get("rpc_cookie_file", ""),
    wallet=wallet_name,
)
wallet = rpc.call("getwalletinfo", [], timeout=15.0)
address = rpc.call("getaddressinfo", [cfg["pool_address"]], timeout=15.0)
if not address.get("ismine"):
    raise SystemExit(
        f"wallet {wallet_name!r} does not own pool address {cfg['pool_address']}"
    )
print(
    f"wallet {wallet_name!r} owns the pool address; "
    f"balance={wallet.get('balance', 0)}"
)
PY
