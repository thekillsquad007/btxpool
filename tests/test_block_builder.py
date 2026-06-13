"""Consensus-facing block and coinbase serialization tests."""

from types import SimpleNamespace

from pool.block_builder import (
    assemble_block_hex,
    block_hash_from_hex,
    build_coinbase_tx,
    compute_template_merkle_root,
    sha256d,
)


def sample_gbt() -> dict:
    return {
        "height": 125_001,
        "coinbasevalue": 5_000_000_000,
        "coinbaseaux": {"flags": "deadbeef"},
        "default_witness_commitment": "6a24aa21a9ed" + "00" * 32,
        "transactions": [],
    }


def test_segwit_coinbase_has_marker_and_bip34_first():
    raw = build_coinbase_tx(sample_gbt(), b"\x51")
    assert raw[4:6] == b"\x00\x01"

    # version + marker/flag + vin count + null outpoint + script length
    script_len_pos = 4 + 2 + 1 + 36
    script_len = raw[script_len_pos]
    script = raw[script_len_pos + 1 : script_len_pos + 1 + script_len]
    assert script.startswith(b"\x03\x49\xe8\x01")
    assert script[4:8] == bytes.fromhex("deadbeef")


def test_btx_block_hash_uses_full_182_byte_header():
    header = bytes(i % 256 for i in range(182))
    block_hex = (header + b"\x00").hex()
    assert block_hash_from_hex(block_hex) == sha256d(header)[::-1].hex()


def test_block_serializes_required_product_payload():
    gbt = sample_gbt()
    payout_script = b"\x51"
    merkle = compute_template_merkle_root(gbt, payout_script)
    job = SimpleNamespace(
        version=0x20000000,
        prev_hash="11" * 32,
        merkle_root=merkle,
        time=1_800_000_000,
        bits="1d00ffff",
        matmul_n=2,
        seed_a="22" * 32,
        seed_b="33" * 32,
        block_height=1,
    )
    raw = bytes.fromhex(
        assemble_block_hex(
            gbt,
            job,
            nonce64=7,
            digest_hex="44" * 32,
            payout_script=payout_script,
            matrix_c=[1, 2, 3, 4],
        )
    )
    assert raw.endswith(
        b"\x00\x00\x04"
        + b"\x01\x00\x00\x00"
        + b"\x02\x00\x00\x00"
        + b"\x03\x00\x00\x00"
        + b"\x04\x00\x00\x00"
    )
