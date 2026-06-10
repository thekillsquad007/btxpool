"""Cached btxd network statistics for the dashboard."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from pool.btx_rpc import BtxRpcClient, RpcError

log = logging.getLogger(__name__)


class NetworkMonitor:
    def __init__(self, rpc: BtxRpcClient, interval: float = 30.0):
        self.rpc = rpc
        self.interval = interval
        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {
            "height": 0,
            "difficulty": 0.0,
            "next_difficulty": 0.0,
            "networkhashps": 0.0,
            "target": "",
            "bits": "",
            "chain": "main",
            "algorithm": "matmul",
            "matmul": {"n": 512, "b": 16, "r": 8},
            "target_spacing_sec": 90.0,
            "coinbasevalue": 0,
            "synced": False,
            "last_error": "",
            "updated_at": 0.0,
        }
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._cache)

    def refresh(self) -> None:
        try:
            mining = self.rpc.call("getmininginfo", timeout=15.0)
            chain = self.rpc.call("getblockchaininfo", timeout=15.0)
            gbt = self.rpc.call(
                "getblocktemplate", [{"rules": ["segwit"]}], timeout=15.0
            )
        except RpcError as e:
            with self._lock:
                self._cache["last_error"] = e.message
            log.debug("network monitor rpc error: %s", e.message)
            return
        except Exception as e:
            with self._lock:
                self._cache["last_error"] = str(e)
            log.debug("network monitor failed: %s", e)
            return

        next_info = mining.get("next") or {}
        matmul = {
            "n": int(mining.get("matmul_n", 512)),
            "b": int(mining.get("matmul_b", 16)),
            "r": int(mining.get("matmul_r", 8)),
        }
        spacing = 90.0
        retention = chain.get("shielded_retention") or {}
        if retention.get("snapshot_target_spacing_seconds"):
            spacing = float(retention["snapshot_target_spacing_seconds"])

        with self._lock:
            self._cache.update({
                "height": int(chain.get("blocks", mining.get("blocks", 0))),
                "difficulty": float(chain.get("difficulty", mining.get("difficulty", 0))),
                "next_difficulty": float(next_info.get("difficulty", 0)),
                "networkhashps": float(mining.get("networkhashps", 0)),
                "target": str(chain.get("target", mining.get("target", ""))),
                "bits": str(chain.get("bits", mining.get("bits", ""))),
                "chain": str(chain.get("chain", mining.get("chain", "main"))),
                "algorithm": str(mining.get("algorithm", "matmul")),
                "matmul": matmul,
                "target_spacing_sec": spacing,
                "coinbasevalue": int(gbt.get("coinbasevalue", 0)),
                "synced": not chain.get("initialblockdownload", True),
                "last_error": "",
                "updated_at": time.time(),
            })

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh()
            self._stop.wait(self.interval)

    def start(self) -> None:
        self.refresh()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="network-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)