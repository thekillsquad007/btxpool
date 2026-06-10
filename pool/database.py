"""SQLite persistence for pool stats."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class PoolDatabase:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS miners (
                    address TEXT PRIMARY KEY,
                    worker_name TEXT NOT NULL DEFAULT '',
                    canonical_name TEXT NOT NULL DEFAULT '',
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    difficulty REAL NOT NULL DEFAULT 0.01,
                    shares_valid INTEGER NOT NULL DEFAULT 0,
                    shares_invalid INTEGER NOT NULL DEFAULT 0,
                    blocks_found INTEGER NOT NULL DEFAULT 0,
                    hashrate_estimate REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    worker_name TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    nonce64 TEXT NOT NULL,
                    difficulty REAL NOT NULL,
                    is_block INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    height INTEGER NOT NULL,
                    hash TEXT NOT NULL DEFAULT '',
                    finder_address TEXT NOT NULL,
                    reward_sats INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pool_stats (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            self._conn.commit()

    def upsert_miner(
        self,
        address: str,
        worker_name: str = "",
        canonical_name: str = "",
        difficulty: float = 0.01,
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO miners (address, worker_name, canonical_name, first_seen, last_seen, difficulty)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    worker_name=excluded.worker_name,
                    canonical_name=excluded.canonical_name,
                    last_seen=excluded.last_seen,
                    difficulty=excluded.difficulty
                """,
                (address, worker_name, canonical_name, now, now, difficulty),
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
    ) -> None:
        now = time.time()
        with self._lock:
            if valid:
                self._conn.execute(
                    """
                    UPDATE miners SET
                        shares_valid = shares_valid + 1,
                        blocks_found = blocks_found + ?,
                        last_seen = ?,
                        hashrate_estimate = hashrate_estimate * 0.9 + ? * 0.1
                    WHERE address = ?
                    """,
                    (1 if is_block else 0, now, difficulty, address),
                )
                self._conn.execute(
                    """
                    INSERT INTO shares (address, worker_name, job_id, nonce64, difficulty, is_block, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (address, worker_name, job_id, nonce64, difficulty, int(is_block), now),
                )
            else:
                self._conn.execute(
                    "UPDATE miners SET shares_invalid = shares_invalid + 1, last_seen = ? WHERE address = ?",
                    (now, address),
                )
            self._conn.commit()

    def record_block(
        self, height: int, finder_address: str, reward_sats: int, block_hash: str = ""
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO blocks (height, hash, finder_address, reward_sats, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (height, block_hash, finder_address, reward_sats, time.time()),
            )
            self._conn.commit()

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
                SELECT address, worker_name, canonical_name, last_seen,
                       difficulty, shares_valid, shares_invalid, blocks_found,
                       hashrate_estimate
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
                "SELECT COUNT(*) AS c, COALESCE(SUM(difficulty), 0) AS work FROM shares"
            ).fetchone()
            blocks = self._conn.execute("SELECT COUNT(*) AS c FROM blocks").fetchone()["c"]
            invalid = self._conn.execute(
                "SELECT COALESCE(SUM(shares_invalid), 0) AS c FROM miners"
            ).fetchone()["c"]
            pool_hashrate = self._conn.execute(
                "SELECT COALESCE(SUM(hashrate_estimate), 0) AS h FROM miners"
            ).fetchone()["h"]
            return {
                "miners": miners,
                "shares": shares["c"],
                "total_work": shares["work"],
                "blocks": blocks,
                "rejected_shares": invalid,
                "miner_hashrate_sum": pool_hashrate,
            }

    def work_window(self, window_sec: float) -> dict[str, Any]:
        cutoff = time.time() - window_sec
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS shares, COALESCE(SUM(difficulty), 0) AS work
                FROM shares WHERE created_at > ?
                """,
                (cutoff,),
            ).fetchone()
            return {
                "shares": int(row["shares"]),
                "work": float(row["work"]),
                "window_sec": window_sec,
            }