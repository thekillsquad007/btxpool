"""SQLite persistence for pool stats."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def miner_canonical_name(
    address: str, worker_name: str = "", canonical_name: str = ""
) -> str:
    if canonical_name:
        return canonical_name
    return f"{address}.{worker_name}" if worker_name else address


class PoolDatabase:
    def __init__(self, path: str, wal: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")
        if wal:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS miners (
                    canonical_name TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    worker_name TEXT NOT NULL DEFAULT '',
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    difficulty REAL NOT NULL DEFAULT 0.01,
                    shares_valid INTEGER NOT NULL DEFAULT 0,
                    shares_invalid INTEGER NOT NULL DEFAULT 0,
                    blocks_found INTEGER NOT NULL DEFAULT 0,
                    hashrate_estimate REAL NOT NULL DEFAULT 0,
                    metrics_updated_at REAL NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_miners_address ON miners(address);

                CREATE TABLE IF NOT EXISTS shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    worker_name TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    nonce64 TEXT NOT NULL,
                    difficulty REAL NOT NULL,
                    work REAL NOT NULL DEFAULT 0,
                    is_block INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS share_submissions (
                    job_id TEXT NOT NULL,
                    ntime INTEGER NOT NULL,
                    nonce64 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (job_id, ntime, nonce64)
                );

                CREATE TABLE IF NOT EXISTS blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    height INTEGER NOT NULL,
                    hash TEXT NOT NULL DEFAULT '',
                    finder_address TEXT NOT NULL,
                    reward_sats INTEGER NOT NULL DEFAULT 0,
                    distributable_sats INTEGER NOT NULL DEFAULT 0,
                    window_work REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'immature',
                    confirmations INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mining_rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    block_id INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    block_hash TEXT NOT NULL DEFAULT '',
                    reward_sats INTEGER NOT NULL DEFAULT 0,
                    distributable_sats INTEGER NOT NULL DEFAULT 0,
                    window_work REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'immature',
                    confirmations INTEGER NOT NULL DEFAULT 0,
                    credited_at REAL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS round_credits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id INTEGER NOT NULL,
                    address TEXT NOT NULL,
                    worker_name TEXT NOT NULL DEFAULT '',
                    work REAL NOT NULL DEFAULT 0,
                    amount_sats INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS miner_balances (
                    address TEXT PRIMARY KEY,
                    immature_sats INTEGER NOT NULL DEFAULT 0,
                    balance_sats INTEGER NOT NULL DEFAULT 0,
                    paid_total_sats INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL,
                    amount_sats INTEGER NOT NULL DEFAULT 0,
                    txid TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS pool_stats (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shares_created ON shares(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_round_credits_address ON round_credits(address);
                CREATE INDEX IF NOT EXISTS idx_payouts_address ON payouts(address);
            """)
            self._migrate_schema()
            self._conn.commit()

    def _migrate_schema(self) -> None:
        cols = {
            row["name"]: row
            for row in self._conn.execute("PRAGMA table_info(miners)").fetchall()
        }
        if "metrics_updated_at" not in cols:
            self._conn.execute(
                "ALTER TABLE miners ADD COLUMN metrics_updated_at REAL NOT NULL DEFAULT 0"
            )
        address_col = cols.get("address")
        if address_col is not None and int(address_col["pk"]) == 1:
            self._migrate_miners_to_canonical_pk()

        block_cols = {
            row["name"]: row
            for row in self._conn.execute("PRAGMA table_info(blocks)").fetchall()
        }
        share_cols = {
            row["name"]: row
            for row in self._conn.execute("PRAGMA table_info(shares)").fetchall()
        }
        if "work" not in share_cols:
            self._conn.execute(
                "ALTER TABLE shares ADD COLUMN work REAL NOT NULL DEFAULT 0"
            )
        for col, typedef in (
            ("distributable_sats", "INTEGER NOT NULL DEFAULT 0"),
            ("window_work", "REAL NOT NULL DEFAULT 0"),
            ("status", "TEXT NOT NULL DEFAULT 'immature'"),
            ("confirmations", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in block_cols:
                self._conn.execute(f"ALTER TABLE blocks ADD COLUMN {col} {typedef}")
        payout_cols = {
            row["name"]: row
            for row in self._conn.execute("PRAGMA table_info(payouts)").fetchall()
        }
        if "request_id" not in payout_cols:
            self._conn.execute(
                "ALTER TABLE payouts ADD COLUMN request_id TEXT NOT NULL DEFAULT ''"
            )
        if "updated_at" not in payout_cols:
            self._conn.execute(
                "ALTER TABLE payouts ADD COLUMN updated_at REAL NOT NULL DEFAULT 0"
            )
        self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payouts_request
            ON payouts(request_id) WHERE request_id != ''
            """
        )

    def _migrate_miners_to_canonical_pk(self) -> None:
        self._conn.executescript("""
            CREATE TABLE miners_new (
                canonical_name TEXT PRIMARY KEY,
                address TEXT NOT NULL,
                worker_name TEXT NOT NULL DEFAULT '',
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                difficulty REAL NOT NULL DEFAULT 0.01,
                shares_valid INTEGER NOT NULL DEFAULT 0,
                shares_invalid INTEGER NOT NULL DEFAULT 0,
                blocks_found INTEGER NOT NULL DEFAULT 0,
                hashrate_estimate REAL NOT NULL DEFAULT 0,
                metrics_updated_at REAL NOT NULL DEFAULT 0
            );

            INSERT INTO miners_new (
                canonical_name, address, worker_name, first_seen, last_seen,
                difficulty, shares_valid, shares_invalid, blocks_found,
                hashrate_estimate, metrics_updated_at
            )
            SELECT
                CASE
                    WHEN canonical_name != '' THEN canonical_name
                    WHEN worker_name != '' THEN address || '.' || worker_name
                    ELSE address
                END,
                address,
                worker_name,
                first_seen,
                last_seen,
                difficulty,
                shares_valid,
                shares_invalid,
                blocks_found,
                hashrate_estimate,
                metrics_updated_at
            FROM miners;

            INSERT OR IGNORE INTO miners_new (
                canonical_name, address, worker_name, first_seen, last_seen, difficulty
            )
            SELECT
                CASE
                    WHEN worker_name != '' THEN address || '.' || worker_name
                    ELSE address
                END,
                address,
                worker_name,
                MIN(created_at),
                MAX(created_at),
                0.01
            FROM shares
            GROUP BY address, worker_name;

            UPDATE miners_new SET shares_valid = (
                SELECT COUNT(*)
                FROM shares
                WHERE CASE
                    WHEN shares.worker_name != '' THEN shares.address || '.' || shares.worker_name
                    ELSE shares.address
                END = miners_new.canonical_name
            );

            UPDATE miners_new SET blocks_found = (
                SELECT COUNT(*)
                FROM shares
                WHERE is_block = 1
                  AND CASE
                      WHEN shares.worker_name != '' THEN shares.address || '.' || shares.worker_name
                      ELSE shares.address
                  END = miners_new.canonical_name
            );

            DROP TABLE miners;
            ALTER TABLE miners_new RENAME TO miners;
            CREATE INDEX IF NOT EXISTS idx_miners_address ON miners(address);
        """)

    def upsert_miner(
        self,
        address: str,
        worker_name: str = "",
        canonical_name: str = "",
        difficulty: float = 0.01,
    ) -> None:
        key = miner_canonical_name(address, worker_name, canonical_name)
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO miners (
                    canonical_name, address, worker_name, first_seen, last_seen, difficulty
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_name) DO UPDATE SET
                    address=excluded.address,
                    worker_name=excluded.worker_name,
                    last_seen=excluded.last_seen,
                    difficulty=excluded.difficulty
                """,
                (key, address, worker_name, now, now, difficulty),
            )
            self._conn.commit()

    def record_share(
        self,
        address: str,
        worker_name: str,
        job_id: str,
        nonce64: str,
        difficulty: float,
        valid: bool,
        is_block: bool = False,
        canonical_name: str = "",
        work: float | None = None,
    ) -> None:
        key = miner_canonical_name(address, worker_name, canonical_name)
        now = time.time()
        with self._lock:
            if valid:
                self._conn.execute(
                    """
                    UPDATE miners SET
                        shares_valid = shares_valid + 1,
                        blocks_found = blocks_found + ?,
                        last_seen = ?
                    WHERE canonical_name = ?
                    """,
                    (1 if is_block else 0, now, key),
                )
                self._conn.execute(
                    """
                    INSERT INTO shares (
                        address, worker_name, job_id, nonce64,
                        difficulty, work, is_block, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        address,
                        worker_name,
                        job_id,
                        nonce64,
                        difficulty,
                        float(difficulty if work is None else work),
                        int(is_block),
                        now,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE miners SET
                        shares_invalid = shares_invalid + 1,
                        last_seen = ?
                    WHERE canonical_name = ?
                    """,
                    (now, key),
                )
            self._conn.commit()

    def claim_share_submission(self, job_id: str, ntime: int, nonce64: str) -> bool:
        """Atomically reject duplicate work before expensive verification."""
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO share_submissions (
                    job_id, ntime, nonce64, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (job_id, int(ntime), nonce64, time.time()),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def record_metrics(self, canonical_name: str, solver_nps: float) -> None:
        if solver_nps <= 0 or not canonical_name:
            return
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                UPDATE miners SET
                    hashrate_estimate = hashrate_estimate * 0.7 + ? * 0.3,
                    metrics_updated_at = ?,
                    last_seen = ?
                WHERE canonical_name = ?
                """,
                (solver_nps, now, now, canonical_name),
            )
            self._conn.commit()

    def active_hashrate_sum(self, max_age_sec: float = 300.0) -> float:
        cutoff = time.time() - max_age_sec
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(hashrate_estimate), 0) AS h
                FROM miners
                WHERE metrics_updated_at > ? AND hashrate_estimate > 0
                """,
                (cutoff,),
            ).fetchone()
            return float(row["h"])

    def record_block(
        self, height: int, finder_address: str, reward_sats: int, block_hash: str = ""
    ) -> None:
        self.record_block_pplns(
            height=height,
            block_hash=block_hash,
            finder_address=finder_address,
            reward_sats=reward_sats,
            distributable_sats=reward_sats,
            window_work=0,
            status="immature",
        )

    def record_block_pplns(
        self,
        *,
        height: int,
        block_hash: str,
        finder_address: str,
        reward_sats: int,
        distributable_sats: int,
        window_work: float,
        status: str = "immature",
    ) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO blocks (
                    height, hash, finder_address, reward_sats, distributable_sats,
                    window_work, status, confirmations, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    height,
                    block_hash,
                    finder_address,
                    reward_sats,
                    distributable_sats,
                    window_work,
                    status,
                    now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def shares_for_pplns_window(self, target_work: float) -> list[dict[str, Any]]:
        if target_work <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT address, worker_name,
                       CASE WHEN work > 0 THEN work ELSE difficulty END AS work,
                       created_at
                FROM shares
                ORDER BY id DESC
                """
            ).fetchall()
        selected: list[dict[str, Any]] = []
        total = 0.0
        for row in rows:
            selected.append(dict(row))
            total += float(row["work"])
            if total >= target_work:
                break
        return selected

    def create_mining_round(
        self,
        *,
        block_id: int,
        height: int,
        block_hash: str,
        reward_sats: int,
        distributable_sats: int,
        window_work: float,
        status: str,
        credits: list[dict[str, Any]],
    ) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO mining_rounds (
                    block_id, height, block_hash, reward_sats, distributable_sats,
                    window_work, status, confirmations, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    block_id,
                    height,
                    block_hash,
                    reward_sats,
                    distributable_sats,
                    window_work,
                    status,
                    now,
                ),
            )
            round_id = int(cur.lastrowid)
            for credit in credits:
                self._conn.execute(
                    """
                    INSERT INTO round_credits (
                        round_id, address, worker_name, work, amount_sats
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        round_id,
                        credit["address"],
                        credit.get("worker_name", ""),
                        float(credit["work"]),
                        int(credit["amount_sats"]),
                    ),
                )
            self._conn.commit()
            return round_id

    def credit_pplns_round(
        self,
        *,
        height: int,
        block_hash: str,
        finder_address: str,
        reward_sats: int,
        distributable_sats: int,
        window_work: float,
        credits: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Persist block, round, credits, and balances in one transaction."""
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                block_cur = self._conn.execute(
                    """
                    INSERT INTO blocks (
                        height, hash, finder_address, reward_sats,
                        distributable_sats, window_work, status,
                        confirmations, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'immature', 0, ?)
                    """,
                    (
                        height,
                        block_hash,
                        finder_address,
                        reward_sats,
                        distributable_sats,
                        window_work,
                        now,
                    ),
                )
                block_id = int(block_cur.lastrowid)
                round_cur = self._conn.execute(
                    """
                    INSERT INTO mining_rounds (
                        block_id, height, block_hash, reward_sats,
                        distributable_sats, window_work, status,
                        confirmations, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'immature', 0, ?)
                    """,
                    (
                        block_id,
                        height,
                        block_hash,
                        reward_sats,
                        distributable_sats,
                        window_work,
                        now,
                    ),
                )
                round_id = int(round_cur.lastrowid)
                amounts: dict[str, int] = {}
                for credit in credits:
                    amount = int(credit["amount_sats"])
                    if amount <= 0:
                        continue
                    address = credit["address"]
                    amounts[address] = amounts.get(address, 0) + amount
                    self._conn.execute(
                        """
                        INSERT INTO round_credits (
                            round_id, address, worker_name, work, amount_sats
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            round_id,
                            address,
                            credit.get("worker_name", ""),
                            float(credit["work"]),
                            amount,
                        ),
                    )
                for address, amount in amounts.items():
                    self._conn.execute(
                        """
                        INSERT INTO miner_balances (
                            address, immature_sats, balance_sats,
                            paid_total_sats, updated_at
                        )
                        VALUES (?, ?, 0, 0, ?)
                        ON CONFLICT(address) DO UPDATE SET
                            immature_sats =
                                miner_balances.immature_sats
                                + excluded.immature_sats,
                            updated_at = excluded.updated_at
                        """,
                        (address, amount, now),
                    )
                self._conn.commit()
                return block_id, round_id
            except Exception:
                self._conn.rollback()
                raise

    def add_immature_credits(self, credits: dict[str, int]) -> None:
        if not credits:
            return
        now = time.time()
        with self._lock:
            for address, amount in credits.items():
                if amount <= 0:
                    continue
                self._conn.execute(
                    """
                    INSERT INTO miner_balances (address, immature_sats, balance_sats, paid_total_sats, updated_at)
                    VALUES (?, ?, 0, 0, ?)
                    ON CONFLICT(address) DO UPDATE SET
                        immature_sats = immature_sats + excluded.immature_sats,
                        updated_at = excluded.updated_at
                    """,
                    (address, amount, now),
                )
            self._conn.commit()

    def rounds_pending_maturity(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, block_id, height, block_hash, status, confirmations
                FROM mining_rounds
                WHERE status = 'immature'
                ORDER BY id ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def update_round_confirmations(self, round_id: int, confirmations: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE mining_rounds SET confirmations = ? WHERE id = ?",
                (confirmations, round_id),
            )
            row = self._conn.execute(
                "SELECT block_id FROM mining_rounds WHERE id = ?", (round_id,)
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE blocks SET confirmations = ? WHERE id = ?",
                    (confirmations, row["block_id"]),
                )
            self._conn.commit()

    def update_round_block_hash(self, round_id: int, block_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE mining_rounds SET block_hash = ? WHERE id = ?",
                (block_hash, round_id),
            )
            row = self._conn.execute(
                "SELECT block_id FROM mining_rounds WHERE id = ?", (round_id,)
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE blocks SET hash = ? WHERE id = ?",
                    (block_hash, row["block_id"]),
                )
            self._conn.commit()

    def mature_round(self, round_id: int) -> int:
        now = time.time()
        with self._lock:
            credits = self._conn.execute(
                """
                SELECT address, SUM(amount_sats) AS amount
                FROM round_credits
                WHERE round_id = ?
                GROUP BY address
                """,
                (round_id,),
            ).fetchall()
            if not credits:
                return 0
            for row in credits:
                amount = int(row["amount"])
                if amount <= 0:
                    continue
                self._conn.execute(
                    """
                    UPDATE miner_balances SET
                        immature_sats = MAX(0, immature_sats - ?),
                        balance_sats = balance_sats + ?,
                        updated_at = ?
                    WHERE address = ?
                    """,
                    (amount, amount, now, row["address"]),
                )
            self._conn.execute(
                """
                UPDATE mining_rounds SET status = 'credited', credited_at = ?
                WHERE id = ?
                """,
                (now, round_id),
            )
            block_row = self._conn.execute(
                "SELECT block_id FROM mining_rounds WHERE id = ?", (round_id,)
            ).fetchone()
            if block_row:
                self._conn.execute(
                    "UPDATE blocks SET status = 'credited' WHERE id = ?",
                    (block_row["block_id"],),
                )
            self._conn.commit()
            return len(credits)

    def orphan_round(self, round_id: int) -> int:
        """Reverse immature credits for a block proven to be orphaned."""
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            round_row = self._conn.execute(
                "SELECT block_id, status FROM mining_rounds WHERE id = ?",
                (round_id,),
            ).fetchone()
            if not round_row or round_row["status"] in ("orphaned", "credited"):
                self._conn.rollback()
                return 0
            credits = self._conn.execute(
                """
                SELECT address, SUM(amount_sats) AS amount
                FROM round_credits
                WHERE round_id = ?
                GROUP BY address
                """,
                (round_id,),
            ).fetchall()
            for row in credits:
                self._conn.execute(
                    """
                    UPDATE miner_balances
                    SET immature_sats = MAX(0, immature_sats - ?),
                        updated_at = ?
                    WHERE address = ?
                    """,
                    (int(row["amount"]), now, row["address"]),
                )
            self._conn.execute(
                """
                UPDATE mining_rounds
                SET status = 'orphaned', confirmations = -1
                WHERE id = ?
                """,
                (round_id,),
            )
            self._conn.execute(
                """
                UPDATE blocks SET status = 'orphaned', confirmations = -1
                WHERE id = ?
                """,
                (int(round_row["block_id"]),),
            )
            self._conn.commit()
            return len(credits)

    def balances_ready_for_payout(self, min_sats: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT address, balance_sats, immature_sats, paid_total_sats
                FROM miner_balances
                WHERE balance_sats >= ?
                ORDER BY balance_sats DESC
                """,
                (min_sats,),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_payout(
        self,
        *,
        address: str,
        amount_sats: int,
        txid: str,
        status: str,
        error: str = "",
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO payouts (
                    request_id, address, amount_sats, txid, status,
                    error, created_at, updated_at
                )
                VALUES ('', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    address,
                    amount_sats,
                    txid,
                    status,
                    error,
                    time.time(),
                    time.time(),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def reserve_payout(self, address: str, amount_sats: int) -> dict[str, Any] | None:
        """Atomically reserve a miner balance before an external wallet call."""
        if amount_sats <= 0:
            return None
        now = time.time()
        request_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT balance_sats FROM miner_balances WHERE address = ?",
                (address,),
            ).fetchone()
            if not row or int(row["balance_sats"]) < amount_sats:
                self._conn.rollback()
                return None
            cur = self._conn.execute(
                """
                INSERT INTO payouts (
                    request_id, address, amount_sats, txid, status,
                    error, created_at, updated_at
                )
                VALUES (?, ?, ?, '', 'reserved', '', ?, ?)
                """,
                (request_id, address, amount_sats, now, now),
            )
            self._conn.execute(
                """
                UPDATE miner_balances SET
                    balance_sats = balance_sats - ?,
                    updated_at = ?
                WHERE address = ?
                """,
                (amount_sats, now, address),
            )
            self._conn.commit()
            return {
                "id": int(cur.lastrowid),
                "request_id": request_id,
                "address": address,
                "amount_sats": amount_sats,
            }

    def mark_payout_sending(self, payout_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE payouts SET status = 'sending', updated_at = ? WHERE id = ?",
                (time.time(), payout_id),
            )
            self._conn.commit()

    def finalize_payout(self, payout_id: int, txid: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT address, amount_sats, status FROM payouts WHERE id = ?",
                (payout_id,),
            ).fetchone()
            if not row or row["status"] == "sent":
                self._conn.rollback()
                return
            self._conn.execute(
                """
                UPDATE payouts
                SET txid = ?, status = 'sent', error = '', updated_at = ?
                WHERE id = ?
                """,
                (txid, now, payout_id),
            )
            self._conn.execute(
                """
                UPDATE miner_balances
                SET paid_total_sats = paid_total_sats + ?, updated_at = ?
                WHERE address = ?
                """,
                (int(row["amount_sats"]), now, row["address"]),
            )
            self._conn.commit()

    def mark_payout_uncertain(self, payout_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE payouts
                SET status = 'uncertain', error = ?, updated_at = ?
                WHERE id = ? AND status != 'sent'
                """,
                (error, time.time(), payout_id),
            )
            self._conn.commit()

    def release_payout(self, payout_id: int, error: str) -> bool:
        """Return a reserved payout to balance after confirmed non-broadcast."""
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT address, amount_sats, status FROM payouts WHERE id = ?",
                (payout_id,),
            ).fetchone()
            if not row or row["status"] not in ("reserved", "failed"):
                self._conn.rollback()
                return False
            self._conn.execute(
                """
                UPDATE miner_balances
                SET balance_sats = balance_sats + ?, updated_at = ?
                WHERE address = ?
                """,
                (int(row["amount_sats"]), now, row["address"]),
            )
            self._conn.execute(
                """
                UPDATE payouts SET status = 'failed', error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, now, payout_id),
            )
            self._conn.commit()
            return True

    def unresolved_payouts(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, request_id, address, amount_sats, txid, status,
                       error, created_at, updated_at
                FROM payouts
                WHERE status IN ('reserved', 'sending', 'uncertain')
                ORDER BY id
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def payouts_sent_since(self, since_ts: float) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(amount_sats), 0) AS total
                FROM payouts
                WHERE status = 'sent' AND created_at >= ?
                """,
                (since_ts,),
            ).fetchone()
            return int(row["total"])

    def debit_balance(self, address: str, amount_sats: int, payout_id: int = 0) -> None:
        """Legacy helper retained for migrations and older integrations."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                UPDATE miner_balances SET
                    balance_sats = MAX(0, balance_sats - ?),
                    paid_total_sats = paid_total_sats + ?,
                    updated_at = ?
                WHERE address = ?
                """,
                (amount_sats, amount_sats, now, address),
            )
            self._conn.commit()

    def get_balance(self, address: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT address, immature_sats, balance_sats, paid_total_sats, updated_at
                FROM miner_balances WHERE address = ?
                """,
                (address,),
            ).fetchone()
            return dict(row) if row else None

    def miners_for_address(self, address: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT canonical_name, address, worker_name, last_seen,
                       difficulty, shares_valid, shares_invalid, blocks_found,
                       hashrate_estimate, metrics_updated_at
                FROM miners
                WHERE address = ?
                ORDER BY shares_valid DESC
                """,
                (address,),
            ).fetchall()
            return [dict(r) for r in rows]

    def recent_credits_for_address(self, address: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT rc.round_id, rc.work, rc.amount_sats, rc.worker_name,
                       mr.height, mr.block_hash, mr.created_at, mr.status
                FROM round_credits rc
                JOIN mining_rounds mr ON mr.id = rc.round_id
                WHERE rc.address = ?
                ORDER BY rc.id DESC
                LIMIT ?
                """,
                (address, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def recent_payouts(self, address: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if address:
                rows = self._conn.execute(
                    """
                    SELECT id, request_id, address, amount_sats, txid, status,
                           error, created_at, updated_at
                    FROM payouts WHERE address = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (address, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT id, request_id, address, amount_sats, txid, status,
                           error, created_at, updated_at
                    FROM payouts ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def recent_rounds(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, height, block_hash, reward_sats, distributable_sats,
                       window_work, status, confirmations, credited_at, created_at
                FROM mining_rounds ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_stat(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO pool_stats (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            self._conn.commit()

    def get_stat(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM pool_stats WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def list_miners(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT canonical_name, address, worker_name, last_seen,
                       difficulty, shares_valid, shares_invalid, blocks_found,
                       hashrate_estimate, metrics_updated_at
                FROM miners ORDER BY shares_valid DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def recent_shares(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT address, worker_name, job_id, nonce64, difficulty, is_block, created_at
                FROM shares ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def recent_blocks(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT height, hash, finder_address, reward_sats, created_at FROM blocks ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def totals(self) -> dict[str, Any]:
        with self._lock:
            miners = self._conn.execute("SELECT COUNT(*) AS c FROM miners").fetchone()["c"]
            shares = self._conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(work), 0) AS work FROM shares"
            ).fetchone()
            blocks = self._conn.execute("SELECT COUNT(*) AS c FROM blocks").fetchone()["c"]
            invalid = self._conn.execute(
                "SELECT COALESCE(SUM(shares_invalid), 0) AS c FROM miners"
            ).fetchone()["c"]
            return {
                "miners": miners,
                "shares": shares["c"],
                "total_work": shares["work"],
                "blocks": blocks,
                "rejected_shares": invalid,
                "miner_hashrate_sum": self.active_hashrate_sum(),
            }

    def worker_work_window(
        self, address: str, worker_name: str, window_sec: float
    ) -> dict[str, Any]:
        cutoff = time.time() - window_sec
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS shares, COALESCE(SUM(work), 0) AS work
                FROM shares
                WHERE created_at > ? AND address = ? AND worker_name = ?
                """,
                (cutoff, address, worker_name),
            ).fetchone()
            return {
                "shares": int(row["shares"]),
                "work": float(row["work"]),
                "window_sec": window_sec,
            }

    def work_window(self, window_sec: float) -> dict[str, Any]:
        cutoff = time.time() - window_sec
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS shares, COALESCE(SUM(work), 0) AS work
                FROM shares WHERE created_at > ?
                """,
                (cutoff,),
            ).fetchone()
            return {
                "shares": int(row["shares"]),
                "work": float(row["work"]),
                "window_sec": window_sec,
            }

    def last_block(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT height, hash, finder_address, reward_sats, created_at
                FROM blocks ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def work_since(self, since_ts: float) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS shares, COALESCE(SUM(work), 0) AS work
                FROM shares WHERE created_at > ?
                """,
                (since_ts,),
            ).fetchone()
            return {
                "shares": int(row["shares"]),
                "work": float(row["work"]),
            }

    def round_start_time(self) -> float:
        """Start of the current mining round (last pool block or first share)."""
        with self._lock:
            block = self._conn.execute(
                "SELECT created_at FROM blocks ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if block:
                return float(block["created_at"])
            row = self._conn.execute(
                "SELECT MIN(created_at) AS t FROM shares"
            ).fetchone()
            if row and row["t"]:
                return float(row["t"])
            return time.time()
