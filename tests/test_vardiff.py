"""Variable difficulty adjustment."""

import time

from pool.stratum.server import StratumServer


def _server() -> StratumServer:
    return StratumServer(
        {
            "vardiff_enabled": True,
            "vardiff_target_seconds": 30,
            "vardiff_min": 0.001,
            "vardiff_max": 2.0,
            "vardiff_max_change": 2.0,
            "vardiff_check_interval": 15,
        },
        jobs=None,
        db=None,
        validator=None,
        rpc=None,
    )


def test_vardiff_raises_difficulty_on_fast_shares():
    srv = _server()
    srv._last_share_time["worker"] = time.time() - 0.5
    new = srv._vardiff("worker", 0.01)
    assert new > 0.01


def test_vardiff_lowers_difficulty_on_slow_shares():
    srv = _server()
    srv._last_share_time["worker"] = time.time() - 120.0
    new = srv._vardiff("worker", 0.01)
    assert new < 0.01


def test_vardiff_first_share_stays_neutral():
    srv = _server()
    new = srv._vardiff("worker", 0.05)
    assert new == 0.05


def test_vardiff_decay_lowers_when_no_share_within_target():
    srv = _server()
    new = srv._vardiff_decay(5.821184, time.time() - 60.0)
    assert new is not None
    assert new < 5.821184


def test_vardiff_decay_waits_until_target_elapsed():
    srv = _server()
    new = srv._vardiff_decay(0.05, time.time() - 20.0)
    assert new is None