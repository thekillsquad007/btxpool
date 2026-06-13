"""Payout safety tests."""

from datetime import datetime, timezone

from pool.btx_rpc import BtxRpcClient
from pool.database import PoolDatabase
from pool.payouts import PayoutWorker, next_daily_run_utc


class NoRpc:
    def send_to_address(self, address: str, amount: float, comment: str = "") -> str:
        raise AssertionError("dry run must not call RPC")

    def call(self, method: str, params: list, timeout: float = 0):
        raise AssertionError("dry run must not call RPC")


class SuccessfulRpc:
    def call(self, method: str, params: list, timeout: float = 0):
        return None

    def get_wallet_balance(self) -> float:
        return 1000.0

    def send_to_address(self, address: str, amount: float, comment: str = "") -> str:
        assert comment.startswith("btxpool:")
        return "txid-1"


class AmbiguousRpc:
    def call(self, method: str, params: list, timeout: float = 0):
        return None

    def get_wallet_balance(self) -> float:
        return 1000.0

    def send_to_address(self, address: str, amount: float, comment: str = "") -> str:
        raise TimeoutError("wallet response timed out")


def test_next_daily_run_is_midnight_utc():
    now = datetime(2026, 6, 14, 18, 30, tzinfo=timezone.utc).timestamp()
    expected = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc).timestamp()
    assert next_daily_run_utc(now) == expected


def test_next_daily_run_does_not_repeat_current_boundary():
    now = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc).timestamp()
    expected = datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc).timestamp()
    assert next_daily_run_utc(now) == expected


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
            "wallet_passphrase_file": str(tmp_path / "passphrase"),
        },
    )
    (tmp_path / "passphrase").write_text("test")
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
            "wallet_passphrase_file": str(tmp_path / "passphrase"),
        },
    )
    (tmp_path / "passphrase").write_text("test")
    result = worker.run_once()
    assert result["paid"] == 1
    balance = db.get_balance("btx1test")
    assert balance["balance_sats"] == 0
    assert balance["paid_total_sats"] == 600_000_000
    assert db.recent_payouts()[0]["status"] == "sent"


def test_ambiguous_payout_is_not_retried_or_returned_to_balance(tmp_path):
    db = _payable_db(tmp_path)
    secret = tmp_path / "passphrase"
    secret.write_text("test")
    worker = PayoutWorker(
        db,
        AmbiguousRpc(),
        {
            "payout_enabled": True,
            "payout_dry_run": False,
            "min_payout_sats": 500_000_000,
            "wallet_passphrase_file": str(secret),
        },
    )
    result = worker.run_once()
    assert result["paid"] == 0
    assert db.get_balance("btx1test")["balance_sats"] == 0
    assert db.unresolved_payouts()[0]["status"] == "uncertain"
    retry = worker.run_once()
    assert retry["skipped"] is True
    assert retry["reason"] == "unresolved_payouts"


def test_wallet_rpc_url_has_no_trailing_slash():
    rpc = BtxRpcClient(
        "http://127.0.0.1:19334",
        "user",
        "password",
        wallet="pool",
    )
    assert rpc.url == "http://127.0.0.1:19334/wallet/pool"


def test_payout_caps_amount_per_address(tmp_path):
    db = _payable_db(tmp_path)
    db._conn.execute(
        "UPDATE miner_balances SET balance_sats = 5000000000 WHERE address = 'btx1test'"
    )
    db._conn.commit()
    secret = tmp_path / "passphrase"
    secret.write_text("test")
    worker = PayoutWorker(
        db,
        SuccessfulRpc(),
        {
            "payout_enabled": True,
            "payout_dry_run": False,
            "min_payout_sats": 500_000_000,
            "payout_max_address_sats": 2_500_000_000,
            "payout_daily_limit_sats": 10_000_000_000,
            "wallet_passphrase_file": str(secret),
        },
    )
    result = worker.run_once()
    assert result["total_sats"] == 2_500_000_000
    assert db.get_balance("btx1test")["balance_sats"] == 2_500_000_000
