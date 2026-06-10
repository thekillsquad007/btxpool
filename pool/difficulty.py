"""Stratum difficulty <-> BTX MatMul target conversion."""

from __future__ import annotations

DIFF1_TARGET = int(
    "00000000ffff00000000000000000000000000000000000000000000000000", 16
)


def _arith_div(target: int, divisor: float) -> int:
    if divisor <= 0:
        return DIFF1_TARGET
    return min(int(target / divisor), DIFF1_TARGET)


def difficulty_to_share_target(difficulty: float, network_target_hex: str | None = None) -> str:
    """Convert pool difficulty to MSB-first display hex share target."""
    base = int(network_target_hex, 16) if network_target_hex else DIFF1_TARGET
    share = _arith_div(base, difficulty)
    return f"{share:064x}"


def target_to_difficulty(share_target_hex: str, network_target_hex: str | None = None) -> float:
    base = int(network_target_hex, 16) if network_target_hex else DIFF1_TARGET
    share = int(share_target_hex, 16)
    if share <= 0:
        return float("inf")
    return base / share


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