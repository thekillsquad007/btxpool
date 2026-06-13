"""Dashboard hashrate unit tests."""

from pool.stats import (
    build_dashboard_stats,
    compute_block_progress,
    estimate_gate_nps_from_raw,
    estimate_network_nps_from_shares,
)


def test_dashboard_exposes_network_scale_pool_rate():
    stats = build_dashboard_stats(
        network={"networkhashps": 3_200_000, "difficulty": 0.07},
        pool_work={
            "work_10m": 1.944,
            "shares_10m": 1944,
            "window_10m": 600,
            "work_1h": 1.944,
            "shares_1h": 1944,
            "window_1h": 3600,
        },
        pool_difficulty=0.001,
        connected_miners=5,
        totals={},
        job={"epsilon_bits": 18},
    )

    expected = estimate_network_nps_from_shares(1944, 600, 0.001)
    assert 58_000_000 < stats["pool"]["hashrate"]["raw"] < 59_000_000
    assert abs(stats["pool"]["hashrate"]["raw"] - expected) < 1000.0
    assert stats["pool"]["hashrate"]["unit"] == "MN/s"
    assert stats["pool"]["hashrate_source"] == "shares"
    assert stats["pool"]["reported_nonce_rate"]["value"] == 0
    assert 49_000 < stats["pool"]["hashrate_gate"]["raw"] < 50_000
    assert stats["pool"]["epsilon_bits"] == 18
    assert stats["pool"]["share_interval_seconds"] == 600 / 1944
    assert stats["pool"]["share_interval"]["display"] == "0.31s"
    assert 1800 < stats["pool"]["network_share_percent"] < 1900


def test_dashboard_prefers_share_network_rate_when_raw_metrics_disagree():
    raw_nps = 1_750_000
    stats = build_dashboard_stats(
        network={"networkhashps": 3_200_000, "difficulty": 0.07},
        pool_work={
            "work_10m": 1.944,
            "shares_10m": 1944,
            "window_10m": 600,
            "work_1h": 1.944,
            "shares_1h": 1944,
            "window_1h": 3600,
        },
        pool_difficulty=0.001,
        connected_miners=1,
        totals={},
        job={"epsilon_bits": 18},
        pool_hashrate_metrics=raw_nps,
    )

    share_network = estimate_network_nps_from_shares(1944, 600, 0.001)
    metrics_gate = estimate_gate_nps_from_raw(raw_nps)

    assert stats["pool"]["reported_nonce_rate"]["raw"] == raw_nps
    assert abs(stats["pool"]["reported_gate_rate"]["raw"] - metrics_gate) < 1.0
    assert abs(stats["pool"]["hashrate"]["raw"] - share_network) < 1000.0
    assert stats["pool"]["hashrate_source"] == "shares"


def test_block_eta_is_memoryless_and_probability_uses_shares():
    progress = compute_block_progress(
        pool_hashrate_hs=678.75,
        network_difficulty=0.07046986360879683,
        round_start_ts=1.0,
        round_shares=27_523,
        share_target_ratio=1_189_154.8083,
    )

    assert 2.2 < progress["progress_percent"] < 2.4
    assert progress["remaining_block_time_seconds"] == progress["expected_block_time_seconds"]
    assert progress["median_block_time_seconds"] < progress["expected_block_time_seconds"]
    assert progress["p95_block_time_seconds"] > progress["expected_block_time_seconds"]