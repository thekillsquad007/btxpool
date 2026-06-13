from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "pool_name": "BTX Family Pool",
    "stratum_host": "0.0.0.0",
    "stratum_port": 3333,
    "api_host": "0.0.0.0",
    "api_port": 8080,
    "cors_origins": [],
    "frontend_port": 3000,
    "rpc_url": "http://127.0.0.1:19334",
    "rpc_user": "",
    "rpc_password": "",
    "rpc_cookie_file": "",
    "rpc_wallet": "",
    "wallet_passphrase_file": "",
    "pool_address": "",
    "pool_fee_percent": 1.0,
    "dev_fee_address": "",
    "payment_mode": "pplns",
    "pplns_window_multiplier": 2.0,
    "pplns_window_work": 0,
    "coinbase_maturity": 150,
    "payout_interval_hours": 24,
    "payout_initial_delay_hours": 24,
    "min_payout_sats": 500_000_000,
    "payout_max_address_sats": 2_500_000_000,
    "payout_daily_limit_sats": 10_000_000_000,
    "payout_wallet_reserve_sats": 100_000_000,
    "payout_enabled": False,
    "payout_dry_run": True,
    "default_difficulty": 0.001,
    "vardiff_enabled": True,
    "vardiff_target_seconds": 30,
    "vardiff_min": 0.001,
    "vardiff_max": 2.0,
    "vardiff_max_change": 2.0,
    "vardiff_check_interval": 15.0,
    "job_poll_interval": 5.0,
    "gbt_longpoll": False,
    "gbt_longpoll_timeout": 60.0,
    "solver_path": "",
    "solver_backend": "cpu",
    "solver_workers": 4,
    "share_verify_queue_size": 64,
    "session_pending_submits": 8,
    "max_stratum_connections": 512,
    "max_stratum_connections_per_ip": 32,
    "stratum_max_message_bytes": 16384,
    "database_path": "data/pool.db",
    "database_wal": True,
    "log_level": "INFO",
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    config_path = Path(path or os.environ.get("BTXPOOL_CONFIG", "config.yaml"))
    if config_path.is_file():
        with config_path.open() as f:
            loaded = yaml.safe_load(f) or {}
        cfg.update(loaded)
    for key in (
        "rpc_user",
        "rpc_password",
        "rpc_cookie_file",
        "rpc_wallet",
        "wallet_passphrase_file",
        "pool_address",
        "solver_path",
    ):
        env_key = f"BTXPOOL_{key.upper()}"
        if os.environ.get(env_key):
            cfg[key] = os.environ[env_key]
    if not cfg.get("pool_address"):
        raise ValueError("pool_address is required (BTX payout address btx1z...)")
    return cfg
