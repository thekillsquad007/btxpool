"""Pool and network hashrate / block-time estimates for the dashboard."""

from __future__ import annotations

import time
from typing import Any

from pool.difficulty import REFERENCE_MATMUL_GATE_PER_S, REFERENCE_POOL_DIFFICULTY


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
    """Bitcoin stratum work (sum of difficulties) -> approximate H/s."""
    if total_difficulty <= 0 or window_sec <= 0:
        return 0.0
    return (total_difficulty * (2**32)) / window_sec


def shares_to_matmul_hashrate(
    total_difficulty: float,
    window_sec: float,
    pool_difficulty: float,
) -> float:
    """Estimate MatMul H/s from accepted share work (fallback when no miner metrics).

    MatMul pool share targets are calibrated for practical share rates, so the raw
    Bitcoin ``work * 2^32 / time`` formula over-counts by orders of magnitude.
    Scale using the reference gate rate at ``REFERENCE_POOL_DIFFICULTY``.
    """
    bitcoin_hs = work_to_hashrate(total_difficulty, window_sec)
    if bitcoin_hs <= 0:
        return 0.0
    ref_diff = max(REFERENCE_POOL_DIFFICULTY, 1e-12)
    diff = max(pool_difficulty, 1e-12)
    # Bitcoin formula assumes diff maps to 2^32 hashes/share; MatMul shares are
    # much easier at the same numeric difficulty.
    bitcoin_at_one_share_per_sec = ref_diff * (2**32)
    scale = REFERENCE_MATMUL_GATE_PER_S / bitcoin_at_one_share_per_sec
    # Adjust if vardiff moved session difficulty away from the reference.
    scale *= ref_diff / diff
    return bitcoin_hs * scale


def block_time_seconds(network_difficulty: float, hashrate_hs: float) -> float | None:
    if network_difficulty <= 0 or hashrate_hs <= 0:
        return None
    return (network_difficulty * (2**32)) / hashrate_hs


def format_target_ratio(share_target_hex: str, block_target_hex: str) -> dict[str, Any]:
    """How much easier the pool share target is vs the network block target."""
    try:
        share = int(share_target_hex, 16)
        block = int(block_target_hex, 16)
    except (TypeError, ValueError):
        return {"ratio": 0.0, "display": "—", "log10": 0.0}
    if block <= 0 or share <= 0:
        return {"ratio": 0.0, "display": "—", "log10": 0.0}
    ratio = share / block
    import math

    log10 = math.log10(ratio) if ratio > 0 else 0.0
    if ratio >= 1e9:
        display = f"{ratio / 1e9:.1f}B×"
    elif ratio >= 1e6:
        display = f"{ratio / 1e6:.1f}M×"
    elif ratio >= 1e3:
        display = f"{ratio / 1e3:.1f}k×"
    elif ratio >= 100:
        display = f"{ratio:.0f}×"
    else:
        display = f"{ratio:.1f}×"
    return {"ratio": ratio, "display": display, "log10": log10}


def compute_block_progress(
    *,
    pool_hashrate_hs: float,
    network_difficulty: float,
    round_start_ts: float,
    round_shares: int = 0,
    round_work: float = 0.0,
    last_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate how far the pool is through the expected time to find a block.

    100% means statistically due for a block; values above 100% mean overdue.
    """
    now = time.time()
    elapsed = max(now - round_start_ts, 0.0)
    expected_sec = block_time_seconds(network_difficulty, pool_hashrate_hs)

    if not expected_sec or expected_sec <= 0:
        return {
            "progress_percent": 0.0,
            "progress_display": "—",
            "bar_fill_percent": 0.0,
            "luck_status": "waiting",
            "luck_message": "Connect miners to estimate block progress",
            "round_elapsed": format_duration(None),
            "round_elapsed_seconds": elapsed,
            "expected_block_time": format_duration(None),
            "expected_block_time_seconds": None,
            "remaining_block_time": format_duration(None),
            "remaining_block_time_seconds": None,
            "round_shares": round_shares,
            "round_work": round_work,
            "round_started_at": round_start_ts,
            "last_block_height": None,
            "last_block_luck_percent": None,
        }

    progress = (elapsed / expected_sec) * 100.0
    remaining = max(expected_sec - elapsed, 0.0)

    if progress < 25:
        luck_status = "early"
        luck_message = "Building toward expected block time"
    elif progress < 100:
        luck_status = "progressing"
        luck_message = f"~{format_duration(remaining)['display']} until statistically due"
    else:
        luck_status = "overdue"
        luck_message = "Past expected time — block could arrive any solve"

    last_block_luck = None
    if last_block and last_block.get("luck_percent") is not None:
        last_block_luck = float(last_block["luck_percent"])

    return {
        "progress_percent": round(progress, 2),
        "progress_display": f"{progress:.1f}%",
        "bar_fill_percent": min(progress, 100.0),
        "luck_status": luck_status,
        "luck_message": luck_message,
        "round_elapsed": format_duration(elapsed),
        "round_elapsed_seconds": elapsed,
        "expected_block_time": format_duration(expected_sec),
        "expected_block_time_seconds": expected_sec,
        "remaining_block_time": format_duration(remaining if progress < 100 else 0),
        "remaining_block_time_seconds": remaining if progress < 100 else 0,
        "round_shares": round_shares,
        "round_work": round_work,
        "round_started_at": round_start_ts,
        "last_block_height": last_block.get("height") if last_block else None,
        "last_block_luck_percent": last_block_luck,
    }


def block_find_luck_percent(
    actual_seconds: float, expected_seconds: float
) -> float | None:
    """Luck for a found block: 100% = on schedule, lower = luckier, higher = unlucky."""
    if actual_seconds <= 0 or expected_seconds <= 0:
        return None
    return (actual_seconds / expected_seconds) * 100.0


def build_mining_context(
    *,
    job: dict[str, Any] | None,
    chain_synced: bool,
    chain_tip_height: int,
    rpc_url: str,
    pool_hashrate_hs: float = 0.0,
    network_hashrate_hs: float = 0.0,
    network_difficulty: float = 0.0,
    share_interval_sec: float | None = None,
    round_start_ts: float | None = None,
    round_shares: int = 0,
    round_work: float = 0.0,
    last_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dashboard context: what block miners hash and odds of a real find."""
    if not job:
        return {
            "active": False,
            "synced": chain_synced,
            "rpc_source": rpc_url,
            "message": "No active job — waiting for btxd template",
        }

    block_target = str(job.get("block_target") or "")
    share_target = str(job.get("share_target") or "")
    easier = format_target_ratio(share_target, block_target)
    mining_height = int(job.get("height") or job.get("block_height") or 0)

    pool_block_sec = None
    if network_difficulty > 0 and pool_hashrate_hs > 0:
        pool_block_sec = block_time_seconds(network_difficulty, pool_hashrate_hs)

    # Fallback: scale observed share interval by target gap.
    est_from_shares = None
    if share_interval_sec and easier["ratio"] > 0:
        est_from_shares = share_interval_sec * easier["ratio"]

    est_block_sec = pool_block_sec or est_from_shares

    progress = compute_block_progress(
        pool_hashrate_hs=pool_hashrate_hs,
        network_difficulty=network_difficulty,
        round_start_ts=round_start_ts or time.time(),
        round_shares=round_shares,
        round_work=round_work,
        last_block=last_block,
    )

    return {
        "active": True,
        "synced": chain_synced,
        "rpc_source": rpc_url,
        "mining_height": mining_height,
        "chain_tip_height": chain_tip_height,
        "job_id": job.get("job_id", ""),
        "prev_hash": job.get("prev_hash", ""),
        "merkle_root": job.get("merkle_root", ""),
        "bits": job.get("bits", ""),
        "block_target": block_target,
        "share_target": share_target,
        "seed_a": job.get("seed_a", ""),
        "seed_b": job.get("seed_b", ""),
        "matmul_n": int(job.get("matmul_n", 512)),
        "matmul_b": int(job.get("matmul_b", 16)),
        "matmul_r": int(job.get("matmul_r", 8)),
        "epsilon_bits": int(job.get("epsilon_bits", 18)),
        "share_easier": easier,
        "can_find_blocks": True,
        "block_submit_path": "Pool verifies digest ≤ block target → submitblock on btxd",
        "est_pool_block_time": format_duration(est_block_sec),
        "est_pool_block_time_seconds": est_block_sec,
        "network_block_time": format_duration(
            block_time_seconds(network_difficulty, network_hashrate_hs)
            if network_difficulty > 0 and network_hashrate_hs > 0
            else None
        ),
        "block_progress": progress,
        "message": (
            f"Miners hash block #{mining_height} (parent {str(job.get('prev_hash', ''))[:16]}…). "
            f"Shares use an easier target ({easier['display']}); a block needs digest ≤ block target."
        ),
    }


def build_dashboard_stats(
    *,
    network: dict[str, Any],
    pool_work: dict[str, Any],
    pool_difficulty: float,
    connected_miners: int,
    totals: dict[str, Any],
    job: dict[str, Any] | None,
    pool_hashrate_metrics: float = 0.0,
    hashrate_source: str = "shares",
) -> dict[str, Any]:
    net_hash = float(network.get("networkhashps") or 0)
    net_diff = float(network.get("difficulty") or 0)
    next_diff = float(network.get("next_difficulty") or 0)
    block_height = int(network.get("height") or 0)
    target_spacing = float(network.get("target_spacing_sec") or 90)

    pool_hash_10m_shares = shares_to_matmul_hashrate(
        pool_work.get("work_10m", 0),
        pool_work.get("window_10m", 600),
        pool_difficulty,
    )
    pool_hash_1h_shares = shares_to_matmul_hashrate(
        pool_work.get("work_1h", 0),
        pool_work.get("window_1h", 3600),
        pool_difficulty,
    )
    pool_hash_10m = pool_hash_10m_shares
    pool_hash_1h = pool_hash_1h_shares
    pool_hash = pool_hash_10m if pool_work.get("shares_10m", 0) >= 3 else pool_hash_1h
    hashrate_source = "shares"

    # Miners often report raw nonce scan rate (N/s) as solver_nps, not matmul H/s.
    # Prefer share-work estimates; only trust metrics when they agree (~5× band).
    if pool_hashrate_metrics > 0:
        if pool_hash > 0:
            ratio = pool_hashrate_metrics / pool_hash
            if 0.2 <= ratio <= 5.0:
                pool_hash = pool_hashrate_metrics
                hashrate_source = "metrics"
        else:
            pool_hash = pool_hashrate_metrics
            hashrate_source = "metrics"

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
            "hashrate_source": hashrate_source,
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