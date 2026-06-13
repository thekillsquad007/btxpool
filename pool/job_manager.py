"""Poll btxd for block templates and build Stratum jobs."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .block_builder import compute_template_merkle_root
from .pplns import pool_fee_bps
from .btx_rpc import BtxRpcClient, RpcError
from .difficulty import difficulty_to_share_target

log = logging.getLogger(__name__)


@dataclass
class PoolJob:
    job_id: str
    version: int
    prev_hash: str
    merkle_root: str
    time: int
    bits: str
    block_target: str
    share_target: str
    clean_jobs: bool
    seed_a: str
    seed_b: str
    block_height: int
    matmul_n: int
    matmul_b: int
    matmul_r: int
    epsilon_bits: int
    nonce64_start: int = 0
    created_at: float = field(default_factory=time.time)
    gbt: dict[str, Any] = field(default_factory=dict)

    def to_notify_params(self) -> list:
        return [
            self.job_id,
            self.version,
            self.prev_hash,
            self.merkle_root,
            self.time,
            self.bits,
            self.share_target,
            self.clean_jobs,
            {
                "seed_a": self.seed_a,
                "seed_b": self.seed_b,
                "block_height": self.block_height,
                "matmul_n": self.matmul_n,
                "matmul_b": self.matmul_b,
                "matmul_r": self.matmul_r,
                "epsilon_bits": self.epsilon_bits,
                "nonce64_start": self.nonce64_start,
            },
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "version": self.version,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "time": self.time,
            "bits": self.bits,
            "block_target": self.block_target,
            "share_target": self.share_target,
            "seed_a": self.seed_a,
            "seed_b": self.seed_b,
            "block_height": self.block_height,
            "matmul_n": self.matmul_n,
            "matmul_b": self.matmul_b,
            "matmul_r": self.matmul_r,
            "epsilon_bits": self.epsilon_bits,
        }


class JobManager:
    def __init__(self, cfg: dict[str, Any], rpc: BtxRpcClient):
        self.cfg = cfg
        self.rpc = rpc
        self._lock = threading.RLock()
        self._jobs: dict[str, PoolJob] = {}
        self._current: PoolJob | None = None
        self._longpollid = ""
        self._pool_script: bytes | None = None
        self._dev_script: bytes | None = None
        self._network_target = ""
        self._height = 0
        self._difficulty = float(cfg.get("default_difficulty", 0.01))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error = ""
        self._synced = False
        self._needs_broadcast = False
        self._broadcast_job: PoolJob | None = None

    @property
    def difficulty(self) -> float:
        with self._lock:
            return self._difficulty

    def set_difficulty(self, value: float) -> None:
        with self._lock:
            self._difficulty = value
            if self._current:
                self._current.share_target = difficulty_to_share_target(
                    value, self._network_target or None
                )

    @property
    def current_job(self) -> PoolJob | None:
        with self._lock:
            return self._current

    def get_job(self, job_id: str) -> PoolJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def share_target_for_difficulty(self, difficulty: float, job: PoolJob) -> str:
        return difficulty_to_share_target(difficulty, job.block_target or None)

    def consume_broadcast_flag(self) -> bool:
        with self._lock:
            if self._needs_broadcast:
                self._needs_broadcast = False
                return True
            return False

    def take_broadcast_job(self) -> PoolJob | None:
        """Return the exact job that requested broadcast (not a later current_job)."""
        with self._lock:
            job = self._broadcast_job
            self._broadcast_job = None
            return job

    def block_key(self) -> tuple[str, int] | None:
        with self._lock:
            if not self._current:
                return None
            return self._block_key(self._current)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "synced": self._synced,
                "height": self._height,
                "difficulty": self._difficulty,
                "network_target": self._network_target,
                "current_job_id": self._current.job_id if self._current else None,
                "last_error": self._last_error,
            }

    def _resolve_address_script(self, address: str, cache_attr: str) -> bytes:
        cached = getattr(self, cache_attr, None)
        if cached is not None:
            return cached
        for method, params in (
            ("validateaddress", [address]),
            ("getaddressinfo", [address]),
        ):
            try:
                info = self.rpc.call(method, params, timeout=10.0)
                spk = info.get("scriptPubKey")
                if spk:
                    script = bytes.fromhex(spk)
                    setattr(self, cache_attr, script)
                    log.info("coinbase script resolved for %s", address[:16])
                    return script
            except RpcError:
                continue
        raise RuntimeError(f"cannot resolve scriptPubKey for address {address}")

    def resolve_pool_script(self) -> bytes:
        return self._resolve_address_script(self.cfg["pool_address"], "_pool_script")

    def resolve_dev_script(self) -> bytes | None:
        dev_address = (self.cfg.get("dev_fee_address") or "").strip()
        pool_address = self.cfg["pool_address"]
        if not dev_address or dev_address == pool_address:
            return None
        return self._resolve_address_script(dev_address, "_dev_script")

    def coinbase_dev_fee_bps(self) -> int:
        """Basis points sent to dev address in coinbase when addresses differ."""
        if not self.resolve_dev_script():
            return 0
        return pool_fee_bps(self.cfg)

    @staticmethod
    def _block_key(job: PoolJob) -> tuple:
        """Identity of the block being mined — seeds/merkle may advance with curtime."""
        return (job.prev_hash, job.block_height)

    @staticmethod
    def _header_fingerprint(job: PoolJob) -> tuple:
        """MatMul work identity — excludes curtime (miners roll ntime per share)."""
        return (
            job.prev_hash,
            job.block_height,
            job.version,
            job.merkle_root,
            job.bits,
        )

    def _job_from_template(
        self, gbt: dict[str, Any], challenge: dict[str, Any], clean: bool
    ) -> PoolJob:
        hc = challenge.get("header_context") or {}
        matmul = gbt.get("matmul") or challenge.get("matmul") or {}
        wp = challenge.get("work_profile") or {}
        epsilon = int(
            wp.get("pre_hash_lottery", {}).get("epsilon_bits")
            or matmul.get("epsilon_bits")
            or gbt.get("epsilon_bits")
            or 18
        )
        height = int(gbt.get("height", hc.get("height", challenge.get("height", 0))))
        prev_hash = (
            gbt.get("previousblockhash")
            or hc.get("previousblockhash", "")
        )
        version = int(gbt.get("version", hc.get("version", 536870912)))
        block_time = int(gbt.get("curtime", hc.get("time", int(time.time()))))
        bits = gbt.get("bits", hc.get("bits", ""))
        block_target = gbt.get("target", challenge.get("target", ""))
        seed_a = hc.get("seed_a", matmul.get("seed_a", gbt.get("seed_a", "0" * 64)))
        seed_b = hc.get("seed_b", matmul.get("seed_b", gbt.get("seed_b", "0" * 64)))

        payout_script = self.resolve_pool_script()
        dev_script = self.resolve_dev_script()
        dev_fee_bps = self.coinbase_dev_fee_bps()
        merkle_root = compute_template_merkle_root(
            gbt,
            payout_script,
            dev_script=dev_script,
            dev_fee_bps=dev_fee_bps,
        )

        job_id = f"btx-{height}-{secrets.token_hex(4)}"
        share_target = difficulty_to_share_target(self._difficulty, block_target or None)

        return PoolJob(
            job_id=job_id,
            version=version,
            prev_hash=prev_hash,
            merkle_root=merkle_root,
            time=block_time,
            bits=bits,
            block_target=block_target,
            share_target=share_target,
            clean_jobs=clean,
            seed_a=seed_a,
            seed_b=seed_b,
            block_height=height,
            matmul_n=int(matmul.get("n", gbt.get("matmul_n", 512))),
            matmul_b=int(matmul.get("b", gbt.get("matmul_b", 16))),
            matmul_r=int(matmul.get("r", gbt.get("matmul_r", 8))),
            epsilon_bits=epsilon,
            gbt=gbt,
        )

    def _fetch_template(self, longpoll: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        params: dict[str, Any] = {"rules": ["segwit"]}
        if longpoll and self._longpollid:
            params["longpollid"] = self._longpollid
        timeout = (
            float(self.cfg.get("gbt_longpoll_timeout", 90.0)) + 10.0
            if longpoll
            else 30.0
        )
        gbt = self.rpc.call("getblocktemplate", [params], timeout=timeout)
        challenge = self.rpc.call("getmatmulchallenge", [], timeout=30.0)
        self._longpollid = gbt.get("longpollid", self._longpollid)
        return gbt, challenge

    def refresh(self, clean: bool = True, *, longpoll: bool | None = None) -> PoolJob | None:
        try:
            info = self.rpc.call("getblockchaininfo", timeout=10.0)
            self._synced = not info.get("initialblockdownload", True)
            self._height = int(info.get("blocks", 0))
            self._last_error = ""
        except Exception as e:
            self._synced = False
            self._last_error = str(e)
            log.warning("chain info failed: %s", e)
            return None

        if not self._synced:
            self._last_error = "btxd still syncing — mining paused until caught up"
            return None

        use_longpoll = (
            bool(self.cfg.get("gbt_longpoll", False))
            if longpoll is None
            else longpoll
        )
        try:
            gbt, challenge = self._fetch_template(longpoll=use_longpoll)
        except RpcError as e:
            self._last_error = e.message
            log.warning("template fetch failed: %s", e)
            return None
        except Exception as e:
            self._last_error = str(e)
            log.warning("template fetch failed: %s", e)
            return None

        job = self._job_from_template(gbt, challenge, clean=clean)
        with self._lock:
            self._network_target = job.block_target
            self._height = job.block_height
            current = self._current

            if current and self._block_key(current) == self._block_key(job):
                if self._header_fingerprint(current) == self._header_fingerprint(job):
                    # A Stratum job is immutable once broadcast. btxd may return
                    # refreshed challenge seeds for the same header, but miners
                    # are still solving the original seeds under this job id.
                    current.gbt = job.gbt
                    current.block_target = job.block_target
                    current.share_target = difficulty_to_share_target(
                        self._difficulty, job.block_target or None
                    )
                    return current

                # Header advanced (curtime, merkle, bits). Keep prior job ids
                # immutable for share validation; issue a new id and notify miners.
                height = job.block_height
                job.job_id = f"btx-{height}-{secrets.token_hex(4)}"
                job.clean_jobs = current.merkle_root != job.merkle_root
                self._jobs[job.job_id] = job
                self._current = job
                self._needs_broadcast = True
                self._broadcast_job = job
            else:
                if len(self._jobs) > 64:
                    oldest = sorted(self._jobs.values(), key=lambda j: j.created_at)[:-64]
                    for old in oldest:
                        self._jobs.pop(old.job_id, None)
                job.clean_jobs = True
                self._jobs[job.job_id] = job
                self._current = job
                self._needs_broadcast = True
                self._broadcast_job = job

        log.info(
            "new job %s height=%d diff=%.4f share_target=%s...",
            job.job_id, job.block_height, self._difficulty, job.share_target[:16],
        )
        return job

    def _poll_loop(self) -> None:
        interval = float(self.cfg.get("job_poll_interval", 10.0))
        while not self._stop.is_set():
            self.refresh(clean=False, longpoll=False)
            self._stop.wait(interval)

    def _longpoll_loop(self) -> None:
        timeout = float(self.cfg.get("gbt_longpoll_timeout", 90.0)) + 5.0
        while not self._stop.is_set():
            if not self._synced:
                self._stop.wait(5.0)
                continue
            try:
                self.refresh(clean=False, longpoll=True)
            except Exception as e:
                log.debug("longpoll refresh: %s", e)
            self._stop.wait(1.0)

    def start(self) -> None:
        self.refresh(clean=True, longpoll=False)
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="job-poller")
        self._thread.start()
        if self.cfg.get("gbt_longpoll", False):
            threading.Thread(
                target=self._longpoll_loop, daemon=True, name="gbt-longpoll"
            ).start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
