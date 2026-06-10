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
    "frontend_port": 3000,
    "rpc_url": "http://127.0.0.1:19334",
    "rpc_user": "",
    "rpc_password": "",
    "rpc_cookie_file": "",
    "pool_address": "",
    "pool_fee_percent": 0.0,
    "default_difficulty": 0.001,
    "vardiff_enabled": True,
    "vardiff_target_seconds": 30,
    "vardiff_min": 0.001,
    "vardiff_max": 100.0,
    "job_poll_interval": 5.0,
    "gbt_longpoll": False,
    "gbt_longpoll_timeout": 60.0,
    "solver_path": "",
    "solver_backend": "cpu",
    "database_path": "data/pool.db",
    "log_level": "INFO",
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    config_path = Path(path or os.environ.get("BTXPOOL_CONFIG", "config.yaml"))
    if config_path.is_file():
        with config_path.open() as f:
            loaded = yaml.safe_load(f) or {}
        cfg.update(loaded)
    for key in ("rpc_user", "rpc_password", "rpc_cookie_file", "pool_address", "solver_path"):
        env_key = f"BTXPOOL_{key.upper()}"
        if os.environ.get(env_key):
            cfg[key] = os.environ[env_key]
    if not cfg.get("pool_address"):
        raise ValueError("pool_address is required (BTX payout address btx1z...)")
    return cfg