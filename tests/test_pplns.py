"""PPLNS fee and window math tests."""

from pool.pplns import distributable_reward, pool_fee_bps, window_work_target


def test_pool_fee_bps():
    assert pool_fee_bps({"pool_fee_percent": 1.0}) == 100
    assert pool_fee_bps({"pool_fee_percent": 0}) == 0
    assert pool_fee_bps({"pool_fee_percent": 2.5}) == 250


def test_distributable_reward():
    reward = 1_000_000_000
    cfg = {"pool_fee_percent": 1.0}
    assert distributable_reward(reward, cfg) == 990_000_000
    assert distributable_reward(reward, {"pool_fee_percent": 0}) == reward


def test_window_work_target():
    cfg = {"pplns_window_multiplier": 2.0}
    assert window_work_target(1.5, cfg) == 3.0
    assert window_work_target(0, cfg) == 2.0
    assert window_work_target(1.5, {"pplns_window_work": 5000}) == 5000