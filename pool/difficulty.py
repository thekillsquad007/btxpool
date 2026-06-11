"""Stratum difficulty <-> BTX MatMul target conversion."""

from __future__ import annotations

DIFF1_TARGET = int(
    "00000000ffff00000000000000000000000000000000000000000000000000", 16
)
MAX_TARGET = (1 << 256) - 1
# MatMul digests are not uniform; Bitcoin-style DIFF1/diff is far too hard on
# current BTX networks. Calibrate so default_difficulty (0.001) lands near a
# target that yields ~minute-scale shares at ~2k post-gate attempts/s.
REFERENCE_POOL_DIFFICULTY = 0.001
REFERENCE_SHARE_TARGET = int(
    "00ffffff00000000000000000000000000000000000000000000000000000000", 16
)
# Typical post-ε gate rate (H/s) for one GPU at REFERENCE_POOL_DIFFICULTY — used to
# convert Bitcoin-style share work into MatMul H/s when miners omit report_metrics.
REFERENCE_MATMUL_GATE_PER_S = 250.0


def difficulty_to_share_target(difficulty: float, network_target_hex: str | None = None) -> str:
    """Convert pool difficulty to MSB-first display hex share target.

    Lower difficulty => easier shares (larger target integer). When a live
    network target is known, scale relative to ``REFERENCE_SHARE_TARGET`` so
    ``REFERENCE_POOL_DIFFICULTY`` matches practical MatMul share rates.
    """
    if difficulty <= 0:
        difficulty = REFERENCE_POOL_DIFFICULTY
    if network_target_hex:
        block_target = int(network_target_hex, 16)
        if block_target <= 0:
            block_target = DIFF1_TARGET
        ref_divisor = block_target / REFERENCE_SHARE_TARGET
        effective_difficulty = difficulty * (ref_divisor / REFERENCE_POOL_DIFFICULTY)
        share = int(block_target / effective_difficulty)
        # Pool shares must not be harder than the block target.
        share = max(share, block_target)
    else:
        share = int(DIFF1_TARGET / difficulty)
    share = min(share, MAX_TARGET)
    return f"{share:064x}"


def target_to_difficulty(share_target_hex: str, network_target_hex: str | None = None) -> float:
    share = int(share_target_hex, 16)
    if share <= 0:
        return float("inf")
    if network_target_hex:
        block_target = int(network_target_hex, 16)
        if block_target > 0 and REFERENCE_SHARE_TARGET > 0:
            ref_divisor = block_target / REFERENCE_SHARE_TARGET
            effective_difficulty = block_target / share
            return effective_difficulty * REFERENCE_POOL_DIFFICULTY / ref_divisor
    return DIFF1_TARGET / share


def compare_digest_le(digest_hex: str, target_hex: str) -> bool:
    """Return True if digest <= target (MSB-first hex display order)."""
    d = bytes.fromhex(digest_hex.zfill(64))
    t = bytes.fromhex(target_hex.zfill(64))
    for i in range(32):
        if d[i] < t[i]:
            return True
        if d[i] > t[i]:
            return False
    return True