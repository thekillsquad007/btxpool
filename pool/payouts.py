"""Scheduled on-chain payouts to miners."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from pool.btx_rpc import BtxRpcClient, RpcError
from pool.database import PoolDatabase

log = logging.getLogger(__name__)

SATS_PER_BTX = 100_000_000


class PayoutWorker:
    def __init__(self, db: PoolDatabase, rpc: BtxRpcClient, cfg: dict[str, Any]):
        self.db = db
        self.rpc = rpc
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def interval_sec(self) -> float:
        hours = float(self.cfg.get("payout_interval_hours", 24))
        return max(3600.0, hours * 3600.0)

    @property
    def min_payout_sats(self) -> int:
        return int(self.cfg.get("min_payout_sats", 500_000_000))

    def start(self) -> None:
        if not self.cfg.get("payout_enabled", True):
            log.info("payout worker disabled (payout_enabled=false)")
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="payout-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        self._stop.wait(120.0)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as e:
                log.error("payout cycle error: %s", e)
            self._stop.wait(self.interval_sec)

    def run_once(self) -> dict[str, Any]:
        if not self.cfg.get("payout_enabled", True):
            return {"skipped": True, "reason": "disabled"}

        with self._lock:
            return self._run_payouts()

    def _run_payouts(self) -> dict[str, Any]:
        dry_run = bool(self.cfg.get("payout_dry_run", False))
        min_sats = self.min_payout_sats
        payable = self.db.balances_ready_for_payout(min_sats)
        if not payable:
            log.debug("payout cycle: no balances >= %.4f BTX", min_sats / SATS_PER_BTX)
            return {"paid": 0, "total_sats": 0}

        paid = 0
        total_sats = 0
        errors: list[str] = []

        for row in payable:
            address = row["address"]
            amount_sats = int(row["balance_sats"])
            if amount_sats < min_sats:
                continue
            amount_btx = amount_sats / SATS_PER_BTX

            if dry_run:
                log.info(
                    "payout dry-run: %.8f BTX -> %s",
                    amount_btx,
                    address[:20],
                )
                payout_id = self.db.record_payout(
                    address=address,
                    amount_sats=amount_sats,
                    txid="dry-run",
                    status="dry_run",
                )
                self.db.debit_balance(address, amount_sats, payout_id=payout_id)
                paid += 1
                total_sats += amount_sats
                continue

            try:
                txid = self.rpc.send_to_address(address, amount_btx)
            except RpcError as e:
                msg = f"{address[:16]}: {e.message}"
                log.error("payout failed %s", msg)
                self.db.record_payout(
                    address=address,
                    amount_sats=amount_sats,
                    txid="",
                    status="failed",
                    error=e.message,
                )
                errors.append(msg)
                continue
            except Exception as e:
                msg = f"{address[:16]}: {e}"
                log.error("payout failed %s", msg)
                errors.append(msg)
                continue

            payout_id = self.db.record_payout(
                address=address,
                amount_sats=amount_sats,
                txid=str(txid),
                status="sent",
            )
            self.db.debit_balance(address, amount_sats, payout_id=payout_id)
            paid += 1
            total_sats += amount_sats
            log.info("payout sent %.8f BTX -> %s txid=%s", amount_btx, address[:20], txid)

        if paid:
            self.db.set_stat("last_payout_at", str(time.time()))
        return {
            "paid": paid,
            "total_sats": total_sats,
            "errors": errors,
            "dry_run": dry_run,
        }