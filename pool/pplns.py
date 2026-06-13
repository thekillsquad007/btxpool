"""PPLNS reward crediting and block maturity handling."""

from __future__ import annotations

import logging
import time
from typing import Any

from pool.block_builder import block_hash_from_hex
from pool.database import PoolDatabase

log = logging.getLogger(__name__)

SATS_PER_BTX = 100_000_000


def pool_fee_bps(cfg: dict[str, Any]) -> int:
    pct = float(cfg.get("pool_fee_percent", 0))
    return max(0, min(10_000, int(round(pct * 100))))


def distributable_reward(reward_sats: int, cfg: dict[str, Any]) -> int:
    bps = pool_fee_bps(cfg)
    if bps <= 0 or reward_sats <= 0:
        return reward_sats
    return reward_sats * (10_000 - bps) // 10_000


def window_work_target(network_difficulty: float, cfg: dict[str, Any]) -> float:
    if cfg.get("pplns_window_work"):
        return float(cfg["pplns_window_work"])
    mult = float(cfg.get("pplns_window_multiplier", 2.0))
    net_diff = max(network_difficulty, 1e-12)
    return max(net_diff * mult, mult)


class PplnsEngine:
    def __init__(self, db: PoolDatabase, cfg: dict[str, Any], rpc=None):
        self.db = db
        self.cfg = cfg
        self.rpc = rpc

    def credit_block(
        self,
        *,
        height: int,
        finder_address: str,
        reward_sats: int,
        block_hex: str | None = None,
        network_difficulty: float = 0.0,
    ) -> dict[str, Any] | None:
        """Run PPLNS distribution for a newly accepted block."""
        block_hash = ""
        if block_hex:
            try:
                block_hash = block_hash_from_hex(block_hex)
            except Exception as e:
                log.warning("block hash compute failed: %s", e)

        distributable = distributable_reward(reward_sats, self.cfg)
        target_work = window_work_target(network_difficulty, self.cfg)
        shares = self.db.shares_for_pplns_window(target_work)
        if not shares:
            log.warning("PPLNS: no shares in window for height=%d", height)
            return None

        total_work = sum(float(s["work"]) for s in shares)
        if total_work <= 0:
            return None

        credits: dict[str, int] = {}
        credit_rows: list[dict[str, Any]] = []
        for share in shares:
            addr = share["address"]
            work = float(share["work"])
            amount = int(distributable * work / total_work)
            if amount <= 0:
                continue
            credits[addr] = credits.get(addr, 0) + amount
            credit_rows.append({
                "address": addr,
                "worker_name": share.get("worker_name", ""),
                "work": work,
                "amount_sats": amount,
            })

        if not credits:
            return None

        block_id, round_id = self.db.credit_pplns_round(
            height=height,
            block_hash=block_hash,
            finder_address=finder_address,
            reward_sats=reward_sats,
            distributable_sats=distributable,
            window_work=total_work,
            credits=credit_rows,
        )

        log.info(
            "PPLNS round=%d height=%d reward=%.4f BTX distributable=%.4f BTX "
            "window_work=%.4f miners=%d",
            round_id,
            height,
            reward_sats / SATS_PER_BTX,
            distributable / SATS_PER_BTX,
            total_work,
            len(credits),
        )
        return {
            "round_id": round_id,
            "block_id": block_id,
            "distributable_sats": distributable,
            "window_work": total_work,
            "miners_credited": len(credits),
        }

    def poll_maturity(self) -> int:
        """Move immature balances to payable when coinbase matures."""
        if not self.rpc:
            return 0
        maturity = int(self.cfg.get("coinbase_maturity", 100))
        rounds = self.db.rounds_pending_maturity()
        matured = 0
        for rnd in rounds:
            block_hash = rnd.get("block_hash") or ""
            height = int(rnd.get("height") or 0)
            confirmations = 0
            if block_hash:
                try:
                    block = self.rpc.call("getblock", [block_hash, 1], timeout=30.0)
                    confirmations = int(block.get("confirmations", 0))
                except Exception as e:
                    log.debug("getblock %s: %s", block_hash[:16], e)
                    continue
            elif height > 0:
                try:
                    hash_hex = self.rpc.call("getblockhash", [height], timeout=15.0)
                    block = self.rpc.call("getblock", [hash_hex, 1], timeout=30.0)
                    confirmations = int(block.get("confirmations", 0))
                    if not block_hash:
                        self.db.update_round_block_hash(int(rnd["id"]), hash_hex)
                except Exception as e:
                    log.debug("maturity height %d: %s", height, e)
                    continue
            else:
                continue

            self.db.update_round_confirmations(int(rnd["id"]), confirmations)
            if confirmations < 0:
                count = self.db.orphan_round(int(rnd["id"]))
                if count:
                    log.warning(
                        "PPLNS round %d orphaned; reversed %d address credits",
                        rnd["id"],
                        count,
                    )
                continue
            if confirmations >= maturity:
                count = self.db.mature_round(int(rnd["id"]))
                if count:
                    matured += 1
                    log.info(
                        "PPLNS round %d matured (%d conf), %d addresses",
                        rnd["id"],
                        confirmations,
                        count,
                    )
        return matured
