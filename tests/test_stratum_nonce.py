"""Stratum notify nonce64_start must stay JSON-safe for btx-gbt-solve."""

import json

from pool.stratum.server import StratumServer

SIGNED_INT64_MAX = (1 << 63) - 1


def test_session_nonce64_start_never_overflows_signed_json_int():
    for extranonce1 in (
        "00000000",
        "7fffffff",
        "83f90dd0",
        "ffffffff",
        "a1b2c3d4e5f60708",
    ):
        start = StratumServer._session_nonce64_start(extranonce1)
        assert 0 <= start <= SIGNED_INT64_MAX
        # Must round-trip through standard JSON parsers used by the solver.
        payload = json.dumps({"nonce_start": start})
        assert json.loads(payload)["nonce_start"] == start


def test_extranonce_shift_32_would_overflow():
    """Document why we do not use extranonce1<<32 in notify."""
    start = int("83f90dd0", 16) << 32
    assert start > SIGNED_INT64_MAX