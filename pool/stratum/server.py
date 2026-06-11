"""Asyncio TCP Stratum server compatible with amdbtx miner."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pool.block_builder import assemble_block_hex
from pool.database import PoolDatabase
from pool.job_manager import JobManager, PoolJob
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
    ):
        self.cfg = cfg
        self.jobs = jobs
        self.db = db
        self.validator = validator
        self.rpc = rpc
        self.host = cfg.get("stratum_host", "0.0.0.0")
        self.port = int(cfg.get("stratum_port", 3333))
        self._sessions: set[StratumSession] = set()
        self._server: asyncio.Server | None = None
        self._vardiff_enabled = bool(cfg.get("vardiff_enabled", True))
        self._vardiff_target = float(cfg.get("vardiff_target_seconds", 30))
        self._vardiff_min = float(cfg.get("vardiff_min", 0.001))
        self._vardiff_max = float(cfg.get("vardiff_max", 100.0))
        self._last_share_time: dict[str, float] = {}

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        log.info("stratum listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        for session in list(self._sessions):
            await session.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def broadcast_job(self, job: PoolJob) -> None:
        params = job.to_notify_params()
        authorized = [s for s in list(self._sessions) if s._authorized]
        if not authorized:
            return
        results = await asyncio.gather(
            *[self._push_job(session, params) for session in authorized],
            return_exceptions=True,
        )
        for session, result in zip(authorized, results):
            if isinstance(result, Exception):
                self._sessions.discard(session)

    async def _push_job(self, session: StratumSession, params: list) -> None:
        await session.send_set_difficulty(session._session_difficulty)
        await session.send_notify(params)

    def _get_notify(self) -> list | None:
        job = self.jobs.current_job
        return job.to_notify_params() if job else None

    def _vardiff(self, canonical_name: str, current: float) -> float:
        if not self._vardiff_enabled:
            return current
        now = time.time()
        last = self._last_share_time.get(canonical_name, now)
        elapsed = max(now - last, 0.1)
        self._last_share_time[canonical_name] = now
        ratio = elapsed / self._vardiff_target
        if ratio > 1.5:
            new_diff = min(current * ratio * 0.8, self._vardiff_max)
        elif ratio < 0.5:
            new_diff = max(current * 0.7, self._vardiff_min)
        else:
            new_diff = current
        return round(new_diff, 6)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        session = StratumSession(
            reader,
            writer,
            on_submit=self._on_submit,
            on_authorize=self._on_authorize,
            on_metrics=self._on_metrics,
            get_job_notify=self._get_notify,
            get_difficulty=lambda: self.jobs.difficulty,
            vardiff_callback=self._vardiff,
            send_canonical_name=bool(self.cfg.get("stratum_send_canonical_name", False)),
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
        canonical = f"{address}.{worker_name}" if worker_name else address
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

        log.info(
            "share submit %s.%s job=%s nonce=%016x",
            address[:16], worker_name, job_id, nonce64,
        )
        loop = asyncio.get_running_loop()
        try:
            verification = await loop.run_in_executor(
                None,
                lambda: self.validator.verify(
                    job.as_dict(),
                    nonce64,
                    ntime,
                    job.share_target,
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
        )
        log.info(
            "share accepted %s.%s job=%s%s",
            address[:16], worker_name, job_id, " BLOCK" if is_block else "",
        )

        if is_block:
            await self._submit_block(job, verification, address)

        return {"accepted": True, "is_block": is_block}

    async def _submit_block(
        self, job: PoolJob, verification: dict[str, Any], finder: str
    ) -> None:
        nonce64 = int(verification["nonce64"])
        digest = verification["digest"]
        ntime = int(verification["ntime"])

        try:
            payout_script = self.jobs.resolve_pool_script()
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
            self.db.record_block(job.block_height, finder, reward)
            log.info(
                "BLOCK FOUND height=%d finder=%s reward=%d sats",
                job.block_height, finder[:16], reward,
            )
            await loop.run_in_executor(None, lambda: self.jobs.refresh(clean=True))
        else:
            log.warning("submitblock rejected: %s", result)