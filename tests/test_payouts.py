"""Payout safety tests."""

from pool.database import PoolDatabase
from pool.payouts import PayoutWorker


class NoRpc:
    def send_to_address(self, address: str, amount: float, comment: str = "") -> str:
        raise AssertionError("dry run must not call RPC")

    def call(self, method: str, params: list, timeout: float = 0):
        raise AssertionError("dry run must not call RPC")


class SuccessfulRpc:
    def send_to_address(self, address: str, amount: float, comment: str = "") -> str:
        assert comment.startswith("btxpool:")
        return "txid-1"


class AmbiguousRpc:
    def send_to_address(self, address: str, amount: float, comment: str = "") -> str:
        raise TimeoutError("wallet response timed out")


def test_dry_run_does_not_debit_balance(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    db.add_immature_credits({"btx1test": 600_000_000})
    db._conn.execute(
        """
        UPDATE miner_balances
        SET immature_sats = 0, balance_sats = 600000000
        WHERE address = 'btx1test'
        """
    )
    db._conn.commit()

    worker = PayoutWorker(
        db,
        NoRpc(),
        {
            "payout_enabled": True,
            "payout_dry_run": True,
            "min_payout_sats": 500_000_000,
        },
    )
    result = worker.run_once()
    assert result["paid"] == 1
    assert db.get_balance("btx1test")["balance_sats"] == 600_000_000


def _payable_db(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    db.add_immature_credits({"btx1test": 600_000_000})
    db._conn.execute(
        """
        UPDATE miner_balances
        SET immature_sats = 0, balance_sats = 600000000
        WHERE address = 'btx1test'
        """
    )
    db._conn.commit()
    return db


def test_successful_payout_reserves_then_finalizes(tmp_path):
    db = _payable_db(tmp_path)
    worker = PayoutWorker(
        db,
        SuccessfulRpc(),
        {
            "payout_enabled": True,
            "payout_dry_run": False,
            "min_payout_sats": 500_000_000,
        },
    )
    result = worker.run_once()
    assert result["paid"] == 1
    balance = db.get_balance("btx1test")
    assert balance["balance_sats"] == 0
    assert balance["paid_total_sats"] == 600_000_000
    assert db.recent_payouts()[0]["status"] == "sent"


def test_ambiguous_payout_is_not_retried_or_returned_to_balance(tmp_path):
    db = _payable_db(tmp_path)
    worker = PayoutWorker(
        db,
        AmbiguousRpc(),
        {
            "payout_enabled": True,
            "payout_dry_run": False,
            "min_payout_sats": 500_000_000,
        },
    )
    result = worker.run_once()
    assert result["paid"] == 0
    assert db.get_balance("btx1test")["balance_sats"] == 0
    assert db.unresolved_payouts()[0]["status"] == "uncertain"
    retry = worker.run_once()
    assert retry["skipped"] is True
    assert retry["reason"] == "unresolved_payouts"
