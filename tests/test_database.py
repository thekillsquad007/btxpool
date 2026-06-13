"""Share uniqueness and PPLNS work persistence tests."""

from pool.database import PoolDatabase


def test_share_submission_claim_is_atomic(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    assert db.claim_share_submission("job", 123, "0001")
    assert not db.claim_share_submission("job", 123, "0001")
    assert db.claim_share_submission("job", 124, "0001")


def test_pplns_window_uses_consensus_work(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    db.upsert_miner("btx1test", "worker")
    db.record_share(
        "btx1test",
        "worker",
        "job",
        "0001",
        difficulty=10.0,
        valid=True,
        work=0.25,
    )
    shares = db.shares_for_pplns_window(0.2)
    assert shares[0]["work"] == 0.25


def test_database_enables_production_pragmas(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    assert db._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db._conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert db._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_orphan_round_reverses_immature_credit(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    _block_id, round_id = db.credit_pplns_round(
        height=100,
        block_hash="abc",
        finder_address="btx1finder",
        reward_sats=1000,
        distributable_sats=990,
        window_work=1.0,
        credits=[
            {
                "address": "btx1miner",
                "worker_name": "rig",
                "work": 1.0,
                "amount_sats": 990,
            }
        ],
    )
    assert db.get_balance("btx1miner")["immature_sats"] == 990
    assert db.orphan_round(round_id) == 1
    assert db.get_balance("btx1miner")["immature_sats"] == 0
    assert db.recent_rounds()[0]["status"] == "orphaned"
    assert db.block_summary()["orphaned"] == 1


def test_block_summary_identifies_latest_pool_block(tmp_path):
    db = PoolDatabase(str(tmp_path / "pool.db"))
    db.record_block(
        height=321,
        block_hash="ab" * 32,
        finder_address="btx1finder",
        reward_sats=500_000_000,
    )

    summary = db.block_summary()
    assert summary["total"] == 1
    assert summary["immature"] == 1
    assert summary["credited"] == 0
    assert summary["orphaned"] == 0
    assert summary["latest"]["height"] == 321
    assert summary["latest"]["hash"] == "ab" * 32
