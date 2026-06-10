"""Stratum difficulty <-> BTX MatMul target conversion."""

from __future__ import annotations

DIFF1_TARGET = int(
    "00000000ffff00000000000000000000000000000000000000000000000000", 16
)
MAX_TARGET = (1 << 256) - 1


def difficulty_to_share_target(difficulty: float, network_target_hex: str | None = None) -> str:
    """Convert pool difficulty to MSB-first display hex share target.

    Stratum convention: lower difficulty => easier shares (larger target integer).
    ``difficulty_to_share_target(0.01)`` is ~100x easier than difficulty 1.0.
    """
    if difficulty <= 0:
        difficulty = 0.01
    share = int(DIFF1_TARGET / difficulty)
    if network_target_hex:
        block_target = int(network_target_hex, 16)
        # Shares must be easier than a block (target value at least block target).
        share = max(share, block_target)
    share = min(share, MAX_TARGET)
    return f"{share:064x}"


def target_to_difficulty(share_target_hex: str, network_target_hex: str | None = None) -> float:
    share = int(share_target_hex, 16)
    if share <= 0:
        return float("inf")
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