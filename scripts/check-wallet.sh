#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

.venv/bin/python <<'PY'
from pool.btx_rpc import BtxRpcClient
from pool.config import load_config
from pathlib import Path

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
addresses = {
    "pool": cfg["pool_address"],
    "dev fee": cfg.get("dev_fee_address", "") or cfg["pool_address"],
}
for label, value in addresses.items():
    address = rpc.call("getaddressinfo", [value], timeout=15.0)
    if not address.get("ismine") or address.get("iswatchonly"):
        raise SystemExit(
            f"wallet {wallet_name!r} cannot spend the {label} address {value}"
        )

passphrase_path = Path(cfg.get("wallet_passphrase_file", "")).expanduser()
if not passphrase_path.is_file():
    raise SystemExit("wallet_passphrase_file is missing")
rpc.call(
    "walletpassphrase",
    [passphrase_path.read_text().strip(), 60],
    timeout=15.0,
)
try:
    integrity = rpc.call("z_verifywalletintegrity", [], timeout=30.0)
finally:
    rpc.call("walletlock", [], timeout=15.0)

required = {
    "master_seed_available": True,
    "pq_descriptors_with_seed": 2,
    "pq_seed_capable_with_seed": 2,
}
for key, expected in required.items():
    actual = integrity.get(key)
    valid = actual is expected if isinstance(expected, bool) else int(actual or 0) >= expected
    if not valid:
        raise SystemExit(
            f"wallet recovery check failed: {key}={actual!r}, expected {expected!r}"
        )
print(
    f"wallet {wallet_name!r} controls the pool/dev address and has complete "
    f"PQ recovery seed material; balance={wallet.get('balance', 0)}"
)
PY
