"""Pool and network hashrate / block-time estimates for the dashboard."""

from __future__ import annotations

import time
from typing import Any


def format_hashrate(hs: float) -> dict[str, Any]:
    """Return human display value + unit for hashes per second."""
    if hs <= 0:
        return {"value": 0, "unit": "H/s", "display": "0 H/s"}
    units = (
        (1e12, "TH/s"),
        (1e9, "GH/s"),
        (1e6, "MH/s"),
        (1e3, "kH/s"),
        (1, "H/s"),
    )
    for scale, unit in units:
        if hs >= scale:
            value = hs / scale
            display = f"{value:.2f} {unit}" if value < 100 else f"{value:.0f} {unit}"
            return {"value": value, "unit": unit, "display": display, "raw": hs}
    return {"value": hs, "unit": "H/s", "display": f"{hs:.0f} H/s", "raw": hs}


def format_duration(seconds: float | None) -> dict[str, Any]:
    if seconds is None or seconds <= 0 or seconds == float("inf"):
        return {"seconds": None, "display": "—"}
    sec = int(seconds)
    if sec < 60:
        return {"seconds": sec, "display": f"{sec}s"}
    if sec < 3600:
        m, s = divmod(sec, 60)
        return {"seconds": sec, "display": f"{m}m {s}s"}
    if sec < 86400:
        h, rem = divmod(sec, 3600)
        m = rem // 60
        return {"seconds": sec, "display": f"{h}h {m}m"}
    d, rem = divmod(sec, 86400)
    h = rem // 3600
    return {"seconds": sec, "display": f"{d}d {h}h"}


def work_to_hashrate(total_difficulty: float, window_sec: float) -> float:
    """Stratum work (sum of difficulties) -> approximate H/s."""
    if total_difficulty <= 0 or window_sec <= 0:
        return 0.0
    return (total_difficulty * (2**32)) / window_sec


def block_time_seconds(network_difficulty: float, hashrate_hs: float) -> float | None:
    if network_difficulty <= 0 or hashrate_hs <= 0:
        return None
    return (network_difficulty * (2**32)) / hashrate_hs


def build_dashboard_stats(
    *,
    network: dict[str, Any],
    pool_work: dict[str, Any],
    pool_difficulty: float,
    connected_miners: int,
    totals: dict[str, Any],
    job: dict[str, Any] | None,
) -> dict[str, Any]:
    net_hash = float(network.get("networkhashps") or 0)
    net_diff = float(network.get("difficulty") or 0)
    next_diff = float(network.get("next_difficulty") or 0)
    block_height = int(network.get("height") or 0)
    target_spacing = float(network.get("target_spacing_sec") or 90)

    pool_hash_10m = work_to_hashrate(pool_work.get("work_10m", 0), pool_work.get("window_10m", 600))
    pool_hash_1h = work_to_hashrate(pool_work.get("work_1h", 0), pool_work.get("window_1h", 3600))
    pool_hash = pool_hash_10m if pool_work.get("shares_10m", 0) >= 3 else pool_hash_1h

    net_block_time = block_time_seconds(net_diff, net_hash)
    pool_block_time = block_time_seconds(net_diff, pool_hash) if pool_hash > 0 else None
    pool_share_time = block_time_seconds(pool_difficulty, pool_hash) if pool_hash > 0 else None

    network_pct = (pool_hash / net_hash * 100) if net_hash > 0 and pool_hash > 0 else 0.0

    return {
        "network": {
            "hashrate": format_hashrate(net_hash),
            "difficulty": net_diff,
            "next_difficulty": next_diff,
            "height": block_height,
            "target": network.get("target", ""),
            "bits": network.get("bits", ""),
            "chain": network.get("chain", "main"),
            "algorithm": network.get("algorithm", "matmul"),
            "matmul": network.get("matmul", {}),
            "block_time": format_duration(net_block_time),
            "block_time_seconds": net_block_time,
            "target_spacing_sec": target_spacing,
        },
        "pool": {
            "hashrate": format_hashrate(pool_hash),
            "hashrate_10m": format_hashrate(pool_hash_10m),
            "hashrate_1h": format_hashrate(pool_hash_1h),
            "difficulty": pool_difficulty,
            "connected_miners": connected_miners,
            "network_share_percent": round(network_pct, 4),
            "block_time": format_duration(pool_block_time),
            "block_time_seconds": pool_block_time,
            "share_interval": format_duration(pool_share_time),
            "share_interval_seconds": pool_share_time,
            "work_10m": pool_work.get("work_10m", 0),
            "shares_10m": pool_work.get("shares_10m", 0),
        },
        "job": job,
        "totals": totals,
        "updated_at": time.time(),
    }