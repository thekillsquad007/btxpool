"""Stratum job lifetime behavior."""

from pool.btx_rpc import RpcError
from pool.job_manager import JobManager


class RefreshingSeedRpc:
    def __init__(self):
        self.challenge_calls = 0

    def call(self, method, params=None, timeout=None):
        if method == "getblockchaininfo":
            return {"blocks": 129_270, "initialblockdownload": False}
        if method == "getblocktemplate":
            return {
                "height": 129_271,
                "version": 0x20000000,
                "previousblockhash": "11" * 32,
                "curtime": 1_781_332_220,
                "bits": "1d0e6361",
                "target": "0000000e6361" + "00" * 26,
                "coinbasevalue": 2_000_000_000,
                "transactions": [],
            }
        if method == "getmatmulchallenge":
            self.challenge_calls += 1
            marker = "22" if self.challenge_calls == 1 else "33"
            return {
                "header_context": {
                    "seed_a": marker * 32,
                    "seed_b": "44" * 32,
                },
                "matmul": {"n": 512, "b": 16, "r": 8},
            }
        if method == "validateaddress":
            return {"scriptPubKey": "51"}
        raise AssertionError(f"unexpected RPC method: {method}")


def test_curtime_only_refresh_keeps_same_job_id():
    class CurtimeRpc(RefreshingSeedRpc):
        def call(self, method, params=None, timeout=None):
            if method == "getblocktemplate":
                self.gbt_calls = getattr(self, "gbt_calls", 0) + 1
                curtime = 1_781_332_220 if self.gbt_calls == 1 else 1_781_332_235
                return {
                    "height": 129_271,
                    "version": 0x20000000,
                    "previousblockhash": "11" * 32,
                    "curtime": curtime,
                    "bits": "1d0e6361",
                    "target": "0000000e6361" + "00" * 26,
                    "coinbasevalue": 2_000_000_000,
                    "transactions": [],
                }
            return super().call(method, params, timeout)

    manager = JobManager(
        {
            "pool_address": "btx1test",
            "dev_fee_address": "",
            "default_difficulty": 0.001,
        },
        CurtimeRpc(),
    )

    first = manager.refresh(clean=True, longpoll=False)
    second = manager.refresh(clean=False, longpoll=False)

    assert first is second
    assert second.time == first.time


def test_same_job_id_keeps_original_broadcast_seeds():
    manager = JobManager(
        {
            "pool_address": "btx1test",
            "dev_fee_address": "",
            "default_difficulty": 0.001,
        },
        RefreshingSeedRpc(),
    )

    first = manager.refresh(clean=True, longpoll=False)
    second = manager.refresh(clean=False, longpoll=False)

    assert first is second
    assert second.seed_a == "22" * 32


def test_template_failure_invalidates_old_jobs():
    class GuardedRpc(RefreshingSeedRpc):
        def call(self, method, params=None, timeout=None):
            if method == "getblocktemplate" and getattr(self, "guarded", False):
                raise RpcError(-9, "insufficient_peer_consensus")
            return super().call(method, params, timeout)

    rpc = GuardedRpc()
    manager = JobManager(
        {
            "pool_address": "btx1test",
            "dev_fee_address": "",
            "default_difficulty": 0.001,
        },
        rpc,
    )
    old_job = manager.refresh(clean=True, longpoll=False)
    assert old_job is not None

    rpc.guarded = True
    assert manager.refresh(clean=False, longpoll=False) is None
    assert manager.current_job is None
    assert manager.get_job(old_job.job_id) is None
    assert manager.status()["last_error"] == "insufficient_peer_consensus"
