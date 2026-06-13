"""Verify submitted Stratum shares by recomputing MatMul digest."""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any

from .block_builder import resolve_header_seeds
from .difficulty import compare_digest_le

log = logging.getLogger(__name__)


class ShareValidator:
    def __init__(
        self,
        solver_path: str = "",
        backend: str = "cpu",
        runtime_ld_path: str = "",
        batch_size: int = 1,
        workers: int = 1,
    ):
        self.solver_path = Path(solver_path).expanduser() if solver_path else None
        self.backend = backend
        self.runtime_ld_path = runtime_ld_path
        self.batch_size = max(int(batch_size), 1)
        self.workers = max(int(workers), 1)
        self._procs: list[subprocess.Popen[str] | None] = [None] * self.workers
        self._ready: list[threading.Event] = [
            threading.Event() for _ in range(self.workers)
        ]
        self._slots: queue.Queue[int] = queue.Queue()
        for slot in range(self.workers):
            self._slots.put(slot)


    @property
    def available(self) -> bool:
        return self.solver_path is not None and self.solver_path.is_file()

    def _ensure_daemon(self, slot: int) -> None:
        proc = self._procs[slot]
        if proc is not None and proc.poll() is None and self._ready[slot].is_set():
            return
        self._stop_daemon(slot)
        self._ready[slot].clear()
        if not self.available:
            raise RuntimeError("solver not configured")

        env = os.environ.copy()
        # Match amdbtx-miner: avoid header-time refresh skew on verify vs submit.
        env.setdefault("BTX_MINER_HEADER_TIME_REFRESH_ATTEMPTS", "4294967295")
        if self.runtime_ld_path:
            parts = [p for p in self.runtime_ld_path.split(":") if p]
            existing = env.get("LD_LIBRARY_PATH", "")
            if existing:
                parts.extend(p for p in existing.split(":") if p and p not in parts)
            env["LD_LIBRARY_PATH"] = ":".join(parts)

        cmd = [
            str(self.solver_path),
            "--daemon",
            "--backend", self.backend,
            "--batch-size", str(self.batch_size),
            "--epsilon-bits", "18",
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self._procs[slot] = proc
        assert proc.stdout is not None
        deadline = 15.0
        import time
        start = time.time()
        while time.time() - start < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if "daemon_ready" in line:
                self._ready[slot].set()
                log.info(
                    "share solver daemon %d/%d ready: %s",
                    slot + 1,
                    self.workers,
                    self.solver_path,
                )
                return
        self._stop_daemon(slot)
        raise RuntimeError("solver daemon failed to start")

    def _stop_daemon(self, slot: int) -> None:
        proc = self._procs[slot]
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._procs[slot] = None
        self._ready[slot].clear()

    def _solve(self, payload: dict[str, Any]) -> dict[str, Any]:
        slot = self._slots.get()
        try:
            self._ensure_daemon(slot)
            proc = self._procs[slot]
            assert proc is not None and proc.stdin is not None
            assert proc.stdout is not None

            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()

            import time
            deadline = time.time() + float(payload.get("max_seconds", 120.0)) + 10.0
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        self._stop_daemon(slot)
                        raise RuntimeError("solver daemon exited unexpectedly")
                    continue
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Solver config:"):
                    log.debug("solver: %s", line)
                    continue
                if line.startswith('{"event"'):
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    log.debug("solver non-json: %s", line[:120])
            raise RuntimeError("solver timed out waiting for result")
        finally:
            self._slots.put(slot)

    def verify(
        self,
        job: dict[str, Any],
        nonce64: int,
        ntime: int,
        share_target_hex: str,
        block_target_hex: str,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError(
                f"solver not configured or missing at {self.solver_path}; "
                "set solver_path to a MineBTX-compatible btx-gbt-solve"
            )

        seed_view = type(
            "SeedJob",
            (),
            {
                "prev_hash": job["prev_hash"],
                "block_height": int(job["block_height"]),
                "version": int(job["version"]),
                "merkle_root": job["merkle_root"],
                "time": int(ntime),
                "bits": job["bits"],
                "matmul_n": int(job.get("matmul_n", 512)),
                "seed_a": job["seed_a"],
                "seed_b": job["seed_b"],
            },
        )()
        seed_a, seed_b = resolve_header_seeds(seed_view, nonce64)

        payload = {
            "version": int(job["version"]),
            "prev_hash": job["prev_hash"],
            "merkle_root": job["merkle_root"],
            "time": int(ntime),
            "bits": job["bits"],
            "seed_a": seed_a.hex(),
            "seed_b": seed_b.hex(),
            "block_height": int(job["block_height"]),
            "matmul_n": int(job.get("matmul_n", 512)),
            "matmul_b": int(job.get("matmul_b", 16)),
            "matmul_r": int(job.get("matmul_r", 8)),
            # Digest-only check at the submitted nonce. Re-running the ε pre-hash
            # gate (epsilon_bits=18) rejects valid HIP shares when CPU SigmaLE
            # disagrees with the GPU gate kernel on the same header.
            "epsilon_bits": 0,
            "nonce_start": int(nonce64),
            "max_tries": 1,
            "max_seconds": 30.0,
            "share_target": share_target_hex,
        }

        try:
            result = self._solve(payload)
        except Exception as e:
            log.warning("share verify solver error: %s", e)
            raise

        if not result.get("found"):
            log.info(
                "verify miss job=%s nonce=%016x ntime=%d job_time=%d "
                "merkle=%s... tries=%s",
                job.get("job_id", "?"),
                nonce64,
                ntime,
                int(job.get("time", 0)),
                str(job.get("merkle_root", ""))[:16],
                result.get("tries_used"),
            )
            return {
                "valid": False,
                "reason": "no_solution",
                "nonce64": nonce64,
            }

        digest = result.get("digest", "")
        is_block = bool(result.get("is_block")) or compare_digest_le(
            digest, block_target_hex
        )
        is_share = compare_digest_le(digest, share_target_hex)
        matrix_c = None

        if is_block:
            block_payload = dict(payload)
            block_payload.update({
                "epsilon_bits": int(job.get("epsilon_bits", 18)),
                "share_target": block_target_hex,
                "include_product_payload": 1,
            })
            try:
                block_result = self._solve(block_payload)
            except Exception as e:
                log.warning("block payload verification failed: %s", e)
                return {
                    "valid": False,
                    "reason": "block_payload_error",
                    "nonce64": nonce64,
                }
            if (
                not block_result.get("found")
                or block_result.get("digest") != digest
                or not block_result.get("is_block")
            ):
                return {
                    "valid": False,
                    "reason": "prehash_miss",
                    "nonce64": nonce64,
                }
            matrix_c = block_result.get("matrix_c")
            expected_words = int(job.get("matmul_n", 512)) ** 2
            if not isinstance(matrix_c, list) or len(matrix_c) != expected_words:
                return {
                    "valid": False,
                    "reason": "missing_product_payload",
                    "nonce64": nonce64,
                }

        if int(result.get("nonce64", nonce64)) != nonce64:
            return {
                "valid": False,
                "reason": "nonce_mismatch",
                "expected": nonce64,
                "got": result.get("nonce64"),
            }

        if int(result.get("ntime", ntime)) != int(ntime):
            return {
                "valid": False,
                "reason": "ntime_mismatch",
                "expected": ntime,
                "got": result.get("ntime"),
            }

        return {
            "valid": is_share,
            "is_block": is_block,
            "digest": digest,
            "nonce64": nonce64,
            "ntime": ntime,
            "reason": "ok" if is_share else "target_miss",
            "matrix_c": matrix_c,
        }

    def close(self) -> None:
        for slot in range(self.workers):
            self._stop_daemon(slot)
