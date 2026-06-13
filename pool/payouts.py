"""Scheduled on-chain payouts to miners."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
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
        self._next_run_at: float | None = None

    @property
    def interval_sec(self) -> float:
        hours = float(self.cfg.get("payout_interval_hours", 24))
        return max(3600.0, hours * 3600.0)

    @property
    def initial_delay_sec(self) -> float:
        hours = float(
            self.cfg.get(
                "payout_initial_delay_hours",
                self.cfg.get("payout_interval_hours", 24),
            )
        )
        return max(120.0, hours * 3600.0)

    @property
    def min_payout_sats(self) -> int:
        return int(self.cfg.get("min_payout_sats", 500_000_000))

    @property
    def next_run_at(self) -> float | None:
        return self._next_run_at

    def start(self) -> None:
        if not self.cfg.get("payout_enabled", True):
            log.info("payout worker disabled (payout_enabled=false)")
            return
        if not self.cfg.get("payout_dry_run", False):
            try:
                wallet = self.rpc.call("getwalletinfo", [], timeout=15.0)
                address = self.rpc.call(
                    "getaddressinfo",
                    [self.cfg.get("pool_address", "")],
                    timeout=15.0,
                )
                if not address.get("ismine", False):
                    raise RuntimeError("configured pool address is not owned by wallet")
                log.info(
                    "payout wallet ready: %s balance=%s",
                    wallet.get("walletname", ""),
                    wallet.get("balance", "unknown"),
                )
            except Exception as e:
                log.error("payout worker refused to start: %s", e)
                return
        unresolved = self.db.unresolved_payouts()
        if unresolved:
            log.error(
                "payout worker blocked: %d unresolved payout(s) require reconciliation",
                len(unresolved),
            )
        self._next_run_at = time.time() + self.initial_delay_sec
        self._thread = threading.Thread(target=self._loop, daemon=True, name="payout-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        self._stop.wait(self.initial_delay_sec)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as e:
                log.error("payout cycle error: %s", e)
            self._next_run_at = time.time() + self.interval_sec
            self._stop.wait(self.interval_sec)

    def run_once(self) -> dict[str, Any]:
        if not self.cfg.get("payout_enabled", True):
            return {"skipped": True, "reason": "disabled"}

        with self._lock:
            return self._run_payouts()

    def _run_payouts(self) -> dict[str, Any]:
        dry_run = bool(self.cfg.get("payout_dry_run", False))
        unresolved = self.db.unresolved_payouts()
        if unresolved and not dry_run:
            return {
                "skipped": True,
                "reason": "unresolved_payouts",
                "unresolved": len(unresolved),
            }
        min_sats = self.min_payout_sats
        max_address_sats = max(
            min_sats,
            int(self.cfg.get("payout_max_address_sats", 2_500_000_000)),
        )
        daily_limit_sats = max(
            min_sats,
            int(self.cfg.get("payout_daily_limit_sats", 10_000_000_000)),
        )
        reserve_sats = max(
            0,
            int(self.cfg.get("payout_wallet_reserve_sats", 100_000_000)),
        )
        sent_last_day = self.db.payouts_sent_since(time.time() - 86400.0)
        daily_remaining = max(0, daily_limit_sats - sent_last_day)
        if daily_remaining < min_sats:
            return {
                "skipped": True,
                "reason": "daily_limit",
                "sent_last_day_sats": sent_last_day,
            }
        payable = self.db.balances_ready_for_payout(min_sats)
        if not payable:
            log.debug("payout cycle: no balances >= %.4f BTX", min_sats / SATS_PER_BTX)
            return {"paid": 0, "total_sats": 0}

        paid = 0
        total_sats = 0
        errors: list[str] = []
        wallet_available_sats: int | None = None
        if not dry_run:
            wallet_available_sats = max(
                0,
                int(self.rpc.get_wallet_balance() * SATS_PER_BTX) - reserve_sats,
            )

        for row in payable:
            address = row["address"]
            amount_sats = min(
                int(row["balance_sats"]),
                max_address_sats,
                daily_remaining,
            )
            if wallet_available_sats is not None:
                amount_sats = min(amount_sats, wallet_available_sats)
            if amount_sats < min_sats:
                continue
            amount_btx = amount_sats / SATS_PER_BTX

            if dry_run:
                log.info(
                    "payout dry-run: %.8f BTX -> %s",
                    amount_btx,
                    address[:20],
                )
                self.db.record_payout(
                    address=address,
                    amount_sats=amount_sats,
                    txid="dry-run",
                    status="dry_run",
                )
                paid += 1
                total_sats += amount_sats
                continue

            reservation = self.db.reserve_payout(address, amount_sats)
            if not reservation:
                continue
            payout_id = int(reservation["id"])
            self.db.mark_payout_sending(payout_id)
            try:
                self._unlock_wallet()
                txid = self.rpc.send_to_address(
                    address,
                    amount_btx,
                    comment=f"btxpool:{reservation['request_id']}",
                )
            except RpcError as e:
                msg = f"{address[:16]}: {e.message}"
                log.error("payout failed %s", msg)
                self.db.mark_payout_uncertain(payout_id, e.message)
                errors.append(msg)
                continue
            except Exception as e:
                msg = f"{address[:16]}: {e}"
                log.error("payout failed %s", msg)
                self.db.mark_payout_uncertain(payout_id, str(e))
                errors.append(msg)
                continue
            finally:
                self._lock_wallet()

            self.db.finalize_payout(payout_id, str(txid))
            paid += 1
            total_sats += amount_sats
            daily_remaining -= amount_sats
            if wallet_available_sats is not None:
                wallet_available_sats -= amount_sats
            log.info("payout sent %.8f BTX -> %s txid=%s", amount_btx, address[:20], txid)

        if paid:
            self.db.set_stat("last_payout_at", str(time.time()))
        return {
            "paid": paid,
            "total_sats": total_sats,
            "errors": errors,
            "dry_run": dry_run,
        }

    def _wallet_passphrase(self) -> str:
        path = str(self.cfg.get("wallet_passphrase_file", "") or "")
        if not path:
            raise RuntimeError("wallet_passphrase_file is not configured")
        secret_path = Path(path).expanduser()
        if not secret_path.is_file():
            raise RuntimeError("wallet passphrase file is missing")
        return secret_path.read_text().strip()

    def _unlock_wallet(self) -> None:
        self.rpc.call(
            "walletpassphrase",
            [self._wallet_passphrase(), 60],
            timeout=15.0,
        )

    def _lock_wallet(self) -> None:
        try:
            self.rpc.call("walletlock", [], timeout=15.0)
        except Exception as e:
            log.error("wallet lock failed after payout attempt: %s", e)
