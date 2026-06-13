"""Network metric collection behavior."""

from pool.btx_rpc import RpcError
from pool.network_monitor import NetworkMonitor


class FakeRpc:
    def call(self, method, params=None, timeout=None):
        if method == "getmininginfo":
            return {
                "blocks": 128414,
                "difficulty": 0.000578,
                "networkhashps": 28084.45,
                "bits": "1e06c100",
                "target": "000006c1",
                "next": {"difficulty": 0.000580},
            }
        if method == "getblockchaininfo":
            return {
                "chain": "main",
                "blocks": 128414,
                "difficulty": 0.000578,
                "initialblockdownload": False,
            }
        if method == "getblocktemplate":
            raise RpcError(-10, "insufficient_peer_consensus")
        raise AssertionError(f"unexpected RPC method: {method}")


def test_metrics_survive_block_template_failure():
    monitor = NetworkMonitor(FakeRpc())

    monitor.refresh()
    stats = monitor.snapshot()

    assert stats["height"] == 128414
    assert stats["difficulty"] == 0.000578
    assert stats["next_difficulty"] == 0.000580
    assert stats["networkhashps"] == 28084.45
    assert stats["synced"] is True
    assert stats["template_available"] is False
    assert stats["template_error"] == "insufficient_peer_consensus"
    assert stats["updated_at"] > 0
