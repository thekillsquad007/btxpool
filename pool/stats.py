"""Pool and network hashrate / block-time estimates for the dashboard."""

from __future__ import annotations

import math
import time
from typing import Any

from pool.difficulty import REFERENCE_MATMUL_GATE_PER_S, REFERENCE_POOL_DIFFICULTY

# BTX work profile (epsilon_bits=18): typical post-σ gate pass rate per raw nonce.
EPSILON18_SIGMA_PASS_RATE = 0.0008553387597203255
# Calibrated share cadence at REFERENCE_POOL_DIFFICULTY on ~REFERENCE_MATMUL_GATE_PER_S.
REFERENCE_SHARE_INTERVAL_SEC = 60.0


def format_hashrate(hs: float) -> dict[str, Any]:
    """Return post-gate MatMul attempt rate (N/s)."""
    return _format_rate(hs, "N/s")


def format_nonce_rate(nps: float) -> dict[str, Any]:
    """Return human display value + unit for raw nonce attempts per second."""
    return _format_rate(nps, "N/s")


def _rate_unit_scales(base_unit: str) -> tuple[tuple[float, str], ...]:
    prefix_unit = base_unit[0]
    return (
        (1e12, f"T{prefix_unit}/s"),
        (1e9, f"G{prefix_unit}/s"),
        (1e6, f"M{prefix_unit}/s"),
        (1e3, f"k{prefix_unit}/s"),
        (1, base_unit),
    )


def _pick_rate_scale(rate: float, base_unit: str = "N/s") -> tuple[float, str]:
    for scale, unit in _rate_unit_scales(base_unit):
        if rate >= scale:
            return scale, unit
    return 1, base_unit


def _format_rate(rate: float, base_unit: str) -> dict[str, Any]:
    if rate <= 0:
        return {"value": 0, "unit": base_unit, "display": f"0 {base_unit}"}
    scale, unit = _pick_rate_scale(rate, base_unit)
    value = rate / scale
    display = f"{value:.2f} {unit}" if value < 100 else f"{value:.0f} {unit}"
    return {"value": value, "unit": unit, "display": display, "raw": rate}


def format_hashrate_like(
    rate: float,
    reference_rate: float,
    base_unit: str = "N/s",
) -> dict[str, Any]:
    """Format *rate* using the same unit prefix as *reference_rate*."""
    if rate <= 0:
        return {"value": 0, "unit": base_unit, "display": f"0 {base_unit}", "raw": 0.0}
    scale, unit = _pick_rate_scale(reference_rate, base_unit)
    value = rate / scale
    if value < 0.01:
        display = f"{value:.4f} {unit}"
    elif value < 100:
        display = f"{value:.2f} {unit}"
    else:
        display = f"{value:.0f} {unit}"
    return {"value": value, "unit": unit, "display": display, "raw": rate}


def format_duration(seconds: float | None) -> dict[str, Any]:
    if seconds is None or seconds <= 0 or seconds == float("inf"):
        return {"seconds": None, "display": "—"}
    if seconds < 1:
        return {"seconds": seconds, "display": f"{seconds:.2f}s"}
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


def estimate_gate_nps_from_shares(
    shares: int,
    window_sec: float,
    pool_difficulty: float,
) -> float:
    """Estimate post-ε gate N/s from accepted-share cadence and pool difficulty."""
    if shares <= 0 or window_sec <= 0:
        return 0.0
    interval = window_sec / shares
    ref_diff = max(REFERENCE_POOL_DIFFICULTY, 1e-12)
    diff = max(pool_difficulty, 1e-12)
    return (
        REFERENCE_MATMUL_GATE_PER_S
        * (REFERENCE_SHARE_INTERVAL_SEC / interval)
        * (ref_diff / diff)
    )


def estimate_gate_nps_from_raw(
    raw_nps: float,
    epsilon_bits: int = 18,
) -> float:
    """Convert miner-reported raw nonce scan rate to gate-equivalent N/s."""
    if raw_nps <= 0:
        return 0.0
    sigma_rate = _sigma_pass_rate(epsilon_bits)
    return raw_nps * sigma_rate


def _sigma_pass_rate(epsilon_bits: int = 18) -> float:
    sigma_rate = EPSILON18_SIGMA_PASS_RATE
    if epsilon_bits != 18:
        sigma_rate *= 2 ** (18 - epsilon_bits)
    return sigma_rate


def gate_nps_to_network_nps(
    gate_nps: float,
    epsilon_bits: int = 18,
) -> float:
    """Convert post-ε gate N/s to btxd networkhashps-equivalent raw N/s."""
    if gate_nps <= 0:
        return 0.0
    sigma_rate = _sigma_pass_rate(epsilon_bits)
    return gate_nps / sigma_rate


def estimate_network_nps_from_shares(
    shares: int,
    window_sec: float,
    pool_difficulty: float,
    epsilon_bits: int = 18,
) -> float:
    """Estimate pool N/s on the same scale as btxd ``networkhashps``."""
    gate_nps = estimate_gate_nps_from_shares(shares, window_sec, pool_difficulty)
    return gate_nps_to_network_nps(gate_nps, epsilon_bits)


def pick_network_hashrate(
    *,
    shares: int,
    window_sec: float,
    pool_difficulty: float,
    raw_metrics_nps: float = 0.0,
    epsilon_bits: int = 18,
) -> tuple[float, str]:
    """Choose best network-scale rate (comparable to ``networkhashps``)."""
    share_network = estimate_network_nps_from_shares(
        shares, window_sec, pool_difficulty, epsilon_bits
    )
    metrics_network = raw_metrics_nps
    if share_network > 0 and metrics_network > 0:
        ratio = metrics_network / share_network
        if 0.2 <= ratio <= 5.0:
            return metrics_network, "metrics"
        return share_network, "shares"
    if metrics_network > 0:
        return metrics_network, "metrics"
    if share_network > 0:
        return share_network, "shares"
    return 0.0, "none"


def pick_gate_hashrate(
    *,
    shares: int,
    window_sec: float,
    pool_difficulty: float,
    raw_metrics_nps: float = 0.0,
    epsilon_bits: int = 18,
) -> tuple[float, str]:
    """Choose best gate-rate estimate and label its source."""
    share_gate = estimate_gate_nps_from_shares(shares, window_sec, pool_difficulty)
    metrics_gate = estimate_gate_nps_from_raw(raw_metrics_nps, epsilon_bits)
    if share_gate > 0 and metrics_gate > 0:
        ratio = metrics_gate / share_gate
        if 0.2 <= ratio <= 5.0:
            return metrics_gate, "metrics_gate"
        return share_gate, "shares"
    if metrics_gate > 0:
        return metrics_gate, "metrics_gate"
    if share_gate > 0:
        return share_gate, "shares"
    return 0.0, "none"


def annotate_worker_hashrate(
    row: dict[str, Any],
    *,
    shares_10m: int,
    window_sec: float,
    pool_difficulty: float,
    epsilon_bits: int = 18,
) -> dict[str, Any]:
    """Add network-scale hashrate fields to a miner row (mutates and returns row)."""
    raw_nps = float(row.get("hashrate_estimate") or 0)
    network_hs, _source = pick_network_hashrate(
        shares=shares_10m,
        window_sec=window_sec,
        pool_difficulty=pool_difficulty,
        raw_metrics_nps=raw_nps,
        epsilon_bits=epsilon_bits,
    )
    share_gate = estimate_gate_nps_from_shares(
        shares_10m, window_sec, pool_difficulty
    )
    row["hashrate"] = format_hashrate(network_hs)
    row["hashrate_gate"] = format_hashrate(
        pick_gate_hashrate(
            shares=shares_10m,
            window_sec=window_sec,
            pool_difficulty=pool_difficulty,
            raw_metrics_nps=raw_nps,
            epsilon_bits=epsilon_bits,
        )[0]
    )
    row["hashrate_share_10m"] = format_hashrate(
        gate_nps_to_network_nps(share_gate, epsilon_bits)
    )
    if raw_nps > 0:
        row["hashrate_nonce_reported"] = format_nonce_rate(raw_nps)
        row["hashrate_gate_reported"] = format_hashrate(
            estimate_gate_nps_from_raw(raw_nps, epsilon_bits)
        )
    return row


def shares_to_matmul_hashrate(
    total_difficulty: float,
    window_sec: float,
    pool_difficulty: float,
) -> float:
    """Backward-compatible alias — expects a share *count* in total_difficulty."""
    return estimate_gate_nps_from_shares(
        int(total_difficulty), window_sec, pool_difficulty
    )


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
    share_target_ratio: float = 0.0,
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

    expected_blocks = (
        round_shares / share_target_ratio
        if round_shares > 0 and share_target_ratio > 0
        else elapsed / expected_sec
    )
    progress = (1.0 - math.exp(-expected_blocks)) * 100.0
    remaining = expected_sec
    median_sec = expected_sec * math.log(2.0)
    p95_sec = expected_sec * -math.log(0.05)
    luck_status = "progressing"
    luck_message = (
        f"At the current rate: 50% chance within "
        f"{format_duration(median_sec)['display']}; "
        f"95% within {format_duration(p95_sec)['display']}"
    )

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
        "median_block_time": format_duration(median_sec),
        "median_block_time_seconds": median_sec,
        "p95_block_time": format_duration(p95_sec),
        "p95_block_time_seconds": p95_sec,
        "remaining_block_time": format_duration(remaining),
        "remaining_block_time_seconds": remaining,
        "expected_blocks": expected_blocks,
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

    # Accepted-share cadence and the exact target ratio provide the most direct
    # estimate and avoid mixing Bitcoin difficulty units with BTX MatMul gates.
    est_block_sec = est_from_shares or pool_block_sec

    progress = compute_block_progress(
        pool_hashrate_hs=pool_hashrate_hs,
        network_difficulty=network_difficulty,
        round_start_ts=round_start_ts or time.time(),
        round_shares=round_shares,
        round_work=round_work,
        share_target_ratio=float(easier.get("ratio") or 0),
        last_block=last_block,
    )

    return {
        "active": True,
        "synced": chain_synced,
        "rpc_source": rpc_url,
        "mining_height": mining_height,
        "chain_tip_height": chain_tip_height,
        "job_id": job.get("job_id", ""),
        "version": int(job.get("version", 0)),
        "prev_hash": job.get("prev_hash", ""),
        "merkle_root": job.get("merkle_root", ""),
        "time": int(job.get("time", 0)),
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
) -> dict[str, Any]:
    net_hash = float(network.get("networkhashps") or 0)
    net_diff = float(network.get("difficulty") or 0)
    next_diff = float(network.get("next_difficulty") or 0)
    block_height = int(network.get("height") or 0)
    target_spacing = float(network.get("target_spacing_sec") or 90)

    epsilon_bits = int((job or {}).get("epsilon_bits", 18))
    shares_10m = int(pool_work.get("shares_10m", 0) or 0)
    shares_1h = int(pool_work.get("shares_1h", 0) or 0)
    window_10m = float(pool_work.get("window_10m", 600) or 600)
    window_1h = float(pool_work.get("window_1h", 3600) or 3600)

    pool_gate_10m = estimate_gate_nps_from_shares(
        shares_10m, window_10m, pool_difficulty
    )
    pool_gate_1h = estimate_gate_nps_from_shares(
        shares_1h, window_1h, pool_difficulty
    )
    pool_hash_10m = estimate_network_nps_from_shares(
        shares_10m, window_10m, pool_difficulty, epsilon_bits
    )
    pool_hash_1h = estimate_network_nps_from_shares(
        shares_1h, window_1h, pool_difficulty, epsilon_bits
    )
    pick_shares = shares_10m if shares_10m >= 3 else shares_1h
    pick_window = window_10m if shares_10m >= 3 else window_1h
    pool_hash, hashrate_source = pick_network_hashrate(
        shares=pick_shares,
        window_sec=pick_window,
        pool_difficulty=pool_difficulty,
        raw_metrics_nps=pool_hashrate_metrics,
        epsilon_bits=epsilon_bits,
    )
    pool_gate, _gate_source = pick_gate_hashrate(
        shares=pick_shares,
        window_sec=pick_window,
        pool_difficulty=pool_difficulty,
        raw_metrics_nps=pool_hashrate_metrics,
        epsilon_bits=epsilon_bits,
    )
    metrics_gate = estimate_gate_nps_from_raw(pool_hashrate_metrics, epsilon_bits)

    net_block_time = block_time_seconds(net_diff, net_hash)
    pool_block_time = block_time_seconds(net_diff, pool_hash) if pool_hash > 0 else None
    pool_share_time = window_10m / shares_10m if shares_10m > 0 else None

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
            "hashrate": format_hashrate_like(pool_hash, net_hash),
            "hashrate_10m": format_hashrate_like(pool_hash_10m, net_hash),
            "hashrate_1h": format_hashrate_like(pool_hash_1h, net_hash),
            "hashrate_gate": format_hashrate(pool_gate),
            "hashrate_gate_10m": format_hashrate(pool_gate_10m),
            "reported_nonce_rate": format_nonce_rate(pool_hashrate_metrics),
            "reported_gate_rate": format_hashrate(metrics_gate),
            "epsilon_bits": epsilon_bits,
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
