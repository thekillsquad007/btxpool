#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIG="${BTXPOOL_CONFIG:-config.yaml}"
BACKUP_DIR="${BTXPOOL_WALLET_BACKUP_DIR:-$HOME/.local/share/btxpool/wallet-backups}"
ARCHIVE_PASSPHRASE_FILE="${BTXPOOL_ARCHIVE_PASSPHRASE_FILE:-$HOME/.local/share/btxpool/secrets/wallet-archive-passphrase}"
RETENTION_DAYS="${BTXPOOL_WALLET_BACKUP_RETENTION_DAYS:-30}"

umask 077
mkdir -p "$BACKUP_DIR"

.venv/bin/python - "$CONFIG" "$BACKUP_DIR" "$ARCHIVE_PASSPHRASE_FILE" <<'PY'
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pool.btx_rpc import BtxRpcClient
from pool.config import load_config

config_path, backup_dir_raw, archive_passphrase_raw = sys.argv[1:4]
cfg = load_config(config_path)
backup_dir = Path(backup_dir_raw).expanduser().resolve()
archive_passphrase_file = Path(archive_passphrase_raw).expanduser()
wallet_passphrase_file = Path(cfg.get("wallet_passphrase_file", "")).expanduser()
wallet_name = cfg.get("rpc_wallet", "")

if not wallet_name:
    raise SystemExit("rpc_wallet is not configured")
if not wallet_passphrase_file.is_file():
    raise SystemExit(f"wallet passphrase file is missing: {wallet_passphrase_file}")
if not archive_passphrase_file.is_file():
    raise SystemExit(
        f"archive passphrase file is missing: {archive_passphrase_file}"
    )

wallet_passphrase = wallet_passphrase_file.read_text().strip()
archive_passphrase = archive_passphrase_file.read_text().strip()
if not wallet_passphrase or not archive_passphrase:
    raise SystemExit("wallet backup passphrase files must not be empty")

rpc = BtxRpcClient(
    cfg["rpc_url"],
    cfg.get("rpc_user", ""),
    cfg.get("rpc_password", ""),
    cfg.get("rpc_cookie_file", ""),
    wallet=wallet_name,
)

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
wallet_file = backup_dir / f"{wallet_name}-{stamp}.dat"
archive_file = backup_dir / f"{wallet_name}-{stamp}.bundle.btx"
try:
    rpc.call("walletpassphrase", [wallet_passphrase, 600], timeout=15.0)
    integrity = rpc.call("z_verifywalletintegrity", [], timeout=30.0)
    required = {
        "master_seed_available": True,
        "pq_descriptors_with_seed": 2,
        "pq_seed_capable_with_seed": 2,
    }
    for key, expected in required.items():
        actual = integrity.get(key)
        if isinstance(expected, bool):
            valid = actual is expected
        else:
            valid = int(actual or 0) >= expected
        if not valid:
            raise SystemExit(
                f"wallet recovery check failed: {key}={actual!r}, "
                f"expected {expected!r}"
            )

    rpc.call("backupwallet", [str(wallet_file)], timeout=120.0)
    bundle = rpc.call(
        "backupwalletbundlearchive",
        [str(archive_file), archive_passphrase, wallet_passphrase, False],
        timeout=300.0,
    )
finally:
    rpc.call("walletlock", [], timeout=15.0)

for path in (wallet_file, archive_file):
    os.chmod(path, 0o600)

summary = {
    "wallet": wallet_name,
    "wallet_file": str(wallet_file),
    "archive_file": str(archive_file),
    "archive_sha256": bundle.get("archive_sha256"),
    "scan_incomplete": bool(integrity.get("scan_incomplete")),
    "recovery_material_complete": True,
}
print(json.dumps(summary, indent=2))
PY

find "$BACKUP_DIR" -type f \
  \( -name '*.dat' -o -name '*.bundle.btx' \) \
  -mtime "+$RETENTION_DAYS" -delete
