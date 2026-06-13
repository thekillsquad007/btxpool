"""Asyncio TCP Stratum server compatible with amdbtx miner."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pool.block_builder import assemble_block_hex
from pool.database import PoolDatabase
from pool.difficulty import target_to_work
from pool.job_manager import JobManager, PoolJob
from pool.pplns import PplnsEngine
from pool.share_validator import ShareValidator
from pool.stratum.session import StratumSession

log = logging.getLogger(__name__)


class StratumServer:
    def __init__(
        self,
        cfg: dict[str, Any],
        jobs: JobManager,
        db: PoolDatabase,
        validator: ShareValidator,
        rpc,
        pplns: PplnsEngine | None = None,
        network_difficulty: callable | None = None,
    ):
        self.cfg = cfg
        self.jobs = jobs
        self.db = db
        self.validator = validator
        self.rpc = rpc
        self.pplns = pplns
        self._network_difficulty = network_difficulty or (lambda: 0.0)
        self.host = cfg.get("stratum_host", "0.0.0.0")
        self.port = int(cfg.get("stratum_port", 3333))
        self._sessions: set[StratumSession] = set()
        self._server: asyncio.Server | None = None
        self._vardiff_enabled = bool(cfg.get("vardiff_enabled", True))
        self._vardiff_target = float(cfg.get("vardiff_target_seconds", 30))
        self._vardiff_min = float(cfg.get("vardiff_min", 0.001))
        self._vardiff_max = float(cfg.get("vardiff_max", 100.0))
        self._vardiff_max_change = float(cfg.get("vardiff_max_change", 2.0))
        self._vardiff_check_interval = float(cfg.get("vardiff_check_interval", 15.0))
        self._last_share_time: dict[str, float] = {}
        self._vardiff_task: asyncio.Task | None = None
        self._verify_workers = max(1, int(cfg.get("solver_workers", 4)))
        self._verify_queue_size = max(
            self._verify_workers,
            int(cfg.get("share_verify_queue_size", 64)),
        )
        self._verify_slots = asyncio.Semaphore(self._verify_workers)
        self._verify_pending = 0
        self._verify_completed = 0
        self._verify_overloaded = 0
        self._verify_total_seconds = 0.0
        self._max_connections = max(
            1, int(cfg.get("max_stratum_connections", 512))
        )
        self._max_connections_per_ip = max(
            1, int(cfg.get("max_stratum_connections_per_ip", 32))
        )
        self._max_message_bytes = max(
            1024, int(cfg.get("stratum_max_message_bytes", 16384))
        )

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            limit=self._max_message_bytes,
        )
        if self._vardiff_enabled:
            self._vardiff_task = asyncio.create_task(
                self._vardiff_loop(), name="vardiff-decay"
            )
        log.info("stratum listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._vardiff_task:
            self._vardiff_task.cancel()
            try:
                await self._vardiff_task
            except asyncio.CancelledError:
                pass
            self._vardiff_task = None
        for session in list(self._sessions):
            await session.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def broadcast_job(self, job: PoolJob) -> None:
        authorized = [s for s in list(self._sessions) if s._authorized]
        if not authorized:
            return
        results = await asyncio.gather(
            *[self._push_job(session, job) for session in authorized],
            return_exceptions=True,
        )
        for session, result in zip(authorized, results):
            if isinstance(result, Exception):
                self._sessions.discard(session)

    # btx-gbt-solve parses JSON job fields as signed int64. extranonce1<<32
    # overflows that limit for ~half of all sessions — keep notify nonce64_start
    # at zero and let miners advance locally within the uint64 nonce space.
    JSON_SAFE_INT64_MAX = (1 << 63) - 1

    @classmethod
    def _session_nonce64_start(cls, extranonce1: str) -> int:
        """Per-session nonce lane that stays inside signed JSON int64."""
        try:
            lane = int(extranonce1, 16) & 0xFFFFF
            start = lane * (1 << 20)
            return min(start, cls.JSON_SAFE_INT64_MAX - (1 << 20))
        except ValueError:
            return 0

    def _notify_params(
        self,
        job: PoolJob,
        difficulty: float | None,
        extranonce1: str = "",
    ) -> list:
        params = job.to_notify_params()
        if difficulty is not None:
            params[6] = self.jobs.share_target_for_difficulty(difficulty, job)
        if len(params) > 8 and isinstance(params[8], dict):
            matmul = dict(params[8])
            matmul["nonce64_start"] = self._session_nonce64_start(extranonce1)
            params[8] = matmul
        return params

    async def _push_job(self, session: StratumSession, job: PoolJob) -> None:
        await session.send_set_difficulty(session._session_difficulty)
        params = self._notify_params(
            job, session._session_difficulty, session._extranonce1
        )
        await session.send_notify(params)

    def _get_notify(
        self, difficulty: float | None = None, extranonce1: str = ""
    ) -> list | None:
        job = self.jobs.current_job
        if not job:
            return None
        return self._notify_params(job, difficulty, extranonce1)

    def _vardiff_factor(self, elapsed: float) -> float:
        # Faster shares than target → raise difficulty; slower → lower.
        factor = self._vardiff_target / max(elapsed, 0.1)
        lo = 1.0 / self._vardiff_max_change
        hi = self._vardiff_max_change
        return max(lo, min(hi, factor))

    def _apply_vardiff(self, current: float, factor: float) -> float:
        new_diff = max(self._vardiff_min, min(current * factor, self._vardiff_max))
        return round(new_diff, 6)

    def _vardiff(self, canonical_name: str, current: float) -> float:
        """Adjust difficulty after an accepted share."""
        if not self._vardiff_enabled:
            return current
        now = time.time()
        last = self._last_share_time.get(canonical_name)
        # First accepted share: don't spike difficulty from a zero elapsed window.
        elapsed = self._vardiff_target if last is None else max(now - last, 0.1)
        self._last_share_time[canonical_name] = now
        return self._apply_vardiff(current, self._vardiff_factor(elapsed))

    def _vardiff_decay(self, current: float, last_event_at: float) -> float | None:
        """Lower difficulty when a miner has not found a share within the target window."""
        if not self._vardiff_enabled or last_event_at <= 0:
            return None
        elapsed = time.time() - last_event_at
        if elapsed < self._vardiff_target:
            return None
        factor = self._vardiff_factor(elapsed)
        if factor >= 1.0:
            return None
        return self._apply_vardiff(current, factor)

    async def _vardiff_loop(self) -> None:
        while True:
            await asyncio.sleep(self._vardiff_check_interval)
            for session in list(self._sessions):
                if not session._authorized:
                    continue
                baseline = session._last_share_at or session._authorized_at
                new_diff = self._vardiff_decay(session._session_difficulty, baseline)
                if new_diff is None or abs(new_diff - session._session_difficulty) <= 1e-9:
                    continue
                try:
                    await session.send_set_difficulty(new_diff)
                    notify = session.get_job_notify(new_diff)
                    if notify:
                        await session.send_notify(notify)
                    log.info(
                        "vardiff decay %s %.6f -> %.6f (no share for %.0fs)",
                        session._canonical_name,
                        session._session_difficulty,
                        new_diff,
                        time.time() - baseline,
                    )
                except Exception as e:
                    log.debug("vardiff decay failed for %s: %s", session._canonical_name, e)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = str(peer[0]) if peer else "unknown"
        same_ip = sum(
            1
            for active in self._sessions
            if active.peer and str(active.peer[0]) == peer_ip
        )
        if (
            len(self._sessions) >= self._max_connections
            or same_ip >= self._max_connections_per_ip
        ):
            log.warning(
                "stratum connection rejected peer=%s active=%d same_ip=%d",
                peer,
                len(self._sessions),
                same_ip,
            )
            writer.close()
            await writer.wait_closed()
            return
        session = StratumSession(
            reader,
            writer,
            on_submit=self._on_submit,
            on_authorize=self._on_authorize,
            on_metrics=self._on_metrics,
            get_job_notify=lambda diff: self._get_notify(
                diff, session._extranonce1
            ),
            get_difficulty=lambda: self.jobs.difficulty,
            vardiff_callback=self._vardiff,
            send_canonical_name=bool(self.cfg.get("stratum_send_canonical_name", False)),
            max_pending_submits=int(self.cfg.get("session_pending_submits", 8)),
            max_message_bytes=self._max_message_bytes,
        )
        self._sessions.add(session)
        try:
            await session.handle()
        finally:
            self._sessions.discard(session)

    async def _on_metrics(self, canonical_name: str, solver_nps: float) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.db.record_metrics(canonical_name, solver_nps),
        )
        log.debug("metrics %s solver_nps=%.0f", canonical_name, solver_nps)

    async def _on_authorize(self, address: str, worker_name: str) -> bool:
        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(
                None,
                lambda: self.rpc.call("validateaddress", [address], timeout=10.0),
            )
        except Exception as e:
            log.warning("address validation failed for %s: %s", address[:16], e)
            return False
        if not info.get("isvalid", False):
            return False
        canonical = f"{address}.{worker_name}" if worker_name else address
        self._last_share_time[canonical] = time.time()
        await loop.run_in_executor(
            None,
            lambda: self.db.upsert_miner(
                address,
                worker_name=worker_name,
                canonical_name=canonical,
                difficulty=self.jobs.difficulty,
            ),
        )
        return True

    async def _on_submit(
        self,
        *,
        address: str,
        worker_name: str,
        canonical_name: str,
        job_id: str,
        extranonce2: str,
        ntime: int,
        nonce64: int,
        difficulty: float,
    ) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        if not job:
            log.info(
                "share rejected %s.%s job=%s: stale or unknown job",
                address[:16], worker_name, job_id,
            )
            return {"accepted": False, "error": "Stale job", "error_code": 21}
        mintime = int(job.gbt.get("mintime", job.time))
        maxtime = int(job.gbt.get("maxtime", int(time.time()) + 7200))
        if ntime < mintime or ntime > maxtime:
            return {"accepted": False, "error": "Invalid ntime", "error_code": 20}

        log.info(
            "share submit %s.%s job=%s nonce=%016x",
            address[:16], worker_name, job_id, nonce64,
        )
        if self._verify_pending >= self._verify_queue_size:
            self._verify_overloaded += 1
            log.warning(
                "share verifier overloaded pending=%d limit=%d",
                self._verify_pending,
                self._verify_queue_size,
            )
            return {
                "accepted": False,
                "error": "Pool verifier busy; retry shortly",
                "error_code": 20,
            }
        loop = asyncio.get_running_loop()
        claimed = await loop.run_in_executor(
            None,
            lambda: self.db.claim_share_submission(
                job_id, ntime, f"{nonce64:016x}"
            ),
        )
        if not claimed:
            return {"accepted": False, "error": "Duplicate share", "error_code": 22}
        share_target = self.jobs.share_target_for_difficulty(difficulty, job)
        share_work = target_to_work(share_target)
        self._verify_pending += 1
        verify_started = time.monotonic()
        try:
            async with self._verify_slots:
                verification = await loop.run_in_executor(
                    None,
                    lambda: self.validator.verify(
                        job.as_dict(),
                        nonce64,
                        ntime,
                        share_target,
                        job.block_target,
                    ),
                )
        except Exception as e:
            log.warning("share verify error: %s", e)
            self.db.record_share(
                address, worker_name, job_id, f"{nonce64:016x}", difficulty, False,
                canonical_name=canonical_name,
            )
            return {"accepted": False, "error": str(e), "error_code": 20}
        finally:
            self._verify_pending -= 1
            self._verify_completed += 1
            self._verify_total_seconds += time.monotonic() - verify_started

        if not verification.get("valid"):
            reason = verification.get("reason", "invalid")
            self.db.record_share(
                address, worker_name, job_id, f"{nonce64:016x}", difficulty, False,
                canonical_name=canonical_name,
            )
            code = 23 if reason in ("target_miss", "no_solution") else 20
            log.info("share rejected %s.%s job=%s: %s", address[:16], worker_name, job_id, reason)
            return {"accepted": False, "error": reason, "error_code": code}

        is_block = bool(verification.get("is_block"))
        self.db.record_share(
            address, worker_name, job_id, f"{nonce64:016x}", difficulty, True, is_block,
            canonical_name=canonical_name,
            work=share_work,
        )
        log.info(
            "share accepted %s.%s job=%s%s",
            address[:16], worker_name, job_id, " BLOCK" if is_block else "",
        )

        if is_block:
            await self._submit_block(job, verification, address)

        return {"accepted": True, "is_block": is_block}

    def status(self) -> dict[str, Any]:
        average_ms = (
            self._verify_total_seconds / self._verify_completed * 1000.0
            if self._verify_completed
            else 0.0
        )
        return {
            "connected_sessions": len(self._sessions),
            "authorized_sessions": sum(1 for s in self._sessions if s._authorized),
            "verifier_workers": self._verify_workers,
            "verifier_pending": self._verify_pending,
            "verifier_queue_limit": self._verify_queue_size,
            "verifier_utilization_percent": round(
                min(100.0, self._verify_pending / self._verify_queue_size * 100.0),
                1,
            ),
            "verifier_completed": self._verify_completed,
            "verifier_overload_rejections": self._verify_overloaded,
            "verifier_average_ms": round(average_ms, 2),
        }

    async def _submit_block(
        self, job: PoolJob, verification: dict[str, Any], finder: str
    ) -> None:
        nonce64 = int(verification["nonce64"])
        digest = verification["digest"]
        ntime = int(verification["ntime"])

        try:
            payout_script = self.jobs.resolve_pool_script()
            dev_script = self.jobs.resolve_dev_script()
            dev_fee_bps = self.jobs.coinbase_dev_fee_bps()
            submit_job = PoolJob(
                job_id=job.job_id,
                version=job.version,
                prev_hash=job.prev_hash,
                merkle_root=job.merkle_root,
                time=ntime,
                bits=job.bits,
                block_target=job.block_target,
                share_target=job.share_target,
                clean_jobs=False,
                seed_a=job.seed_a,
                seed_b=job.seed_b,
                block_height=job.block_height,
                matmul_n=job.matmul_n,
                matmul_b=job.matmul_b,
                matmul_r=job.matmul_r,
                epsilon_bits=job.epsilon_bits,
            )
            block_hex = assemble_block_hex(
                job.gbt,
                submit_job,
                nonce64,
                digest,
                payout_script,
                dev_script=dev_script,
                dev_fee_bps=dev_fee_bps,
                matrix_c=verification.get("matrix_c"),
            )
        except Exception as e:
            log.error("block assembly failed: %s", e)
            return

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: self.rpc.call("submitblock", [block_hex], timeout=120.0)
            )
        except Exception as e:
            log.error("submitblock failed: %s", e)
            return

        if result in (None, "null", ""):
            reward = int(job.gbt.get("coinbasevalue", 0))
            log.info(
                "BLOCK FOUND height=%d finder=%s reward=%d sats",
                job.block_height, finder[:16], reward,
            )
            if self.pplns and self.cfg.get("payment_mode", "pplns") == "pplns":
                net_diff = float(self._network_difficulty())
                await loop.run_in_executor(
                    None,
                    lambda: self.pplns.credit_block(
                        height=job.block_height,
                        finder_address=finder,
                        reward_sats=reward,
                        block_hex=block_hex,
                        network_difficulty=net_diff,
                    ),
                )
            else:
                self.db.record_block(job.block_height, finder, reward)
            await loop.run_in_executor(None, lambda: self.jobs.refresh(clean=True))
        else:
            log.warning("submitblock rejected: %s", result)
