"""Verify submitted Stratum shares by recomputing MatMul digest."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from .difficulty import compare_digest_le

log = logging.getLogger(__name__)


class ShareValidator:
    def __init__(
        self,
        solver_path: str = "",
        backend: str = "cpu",
        runtime_ld_path: str = "",
    ):
        self.solver_path = Path(solver_path).expanduser() if solver_path else None
        self.backend = backend
        self.runtime_ld_path = runtime_ld_path
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()


    @property
    def available(self) -> bool:
        return self.solver_path is not None and self.solver_path.is_file()

    def _ensure_daemon(self) -> None:
        if self._proc is not None and self._proc.poll() is None and self._ready.is_set():
            return
        self._stop_daemon()
        self._ready.clear()
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
            "--batch-size", "1",
            "--epsilon-bits", "18",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self._proc.stdout is not None
        deadline = 15.0
        import time
        start = time.time()
        while time.time() - start < deadline:
            line = self._proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if "daemon_ready" in line:
                self._ready.set()
                log.info("share solver daemon ready: %s", self.solver_path)
                return
        self._stop_daemon()
        raise RuntimeError("solver daemon failed to start")

    def _stop_daemon(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        self._ready.clear()

    def _solve(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_daemon()
            assert self._proc is not None and self._proc.stdin is not None
            assert self._proc.stdout is not None

            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()

            import time
            deadline = time.time() + float(payload.get("max_seconds", 120.0)) + 10.0
            while time.time() < deadline:
                line = self._proc.stdout.readline()
                if not line:
                    if self._proc.poll() is not None:
                        self._stop_daemon()
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
                "set solver_path to btx-gbt-solve-hip (from amdbtx install)"
            )

        payload = {
            "version": int(job["version"]),
            "prev_hash": job["prev_hash"],
            "merkle_root": job["merkle_root"],
            "time": int(ntime),
            "bits": job["bits"],
            "seed_a": job["seed_a"],
            "seed_b": job["seed_b"],
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
        }

    def close(self) -> None:
        self._stop_daemon()