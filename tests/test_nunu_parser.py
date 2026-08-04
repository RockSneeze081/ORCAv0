import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

import pytest
from nunu_parser import (
    BODY_LEN,
    SYNC_WORD,
    ParseError,
    PacketType,
    build_body,
    find_packets,
    parse_body,
)


def test_round_trip_message():
    body = build_body(PacketType.MESSAGE, b"hello mesh")
    packet = parse_body(body)
    assert packet.packet_type is PacketType.MESSAGE
    assert packet.text() == "hello mesh"
    assert not packet.is_encrypted


def test_round_trip_encrypted():
    nonce = bytes(range(13))
    body = build_body(PacketType.ENCRYPTED_MESSAGE, b"\x01\x02\x03", nonce)
    packet = parse_body(body)
    assert packet.is_encrypted
    assert packet.nonce == nonce


def test_wrong_length_raises():
    with pytest.raises(ParseError):
        parse_body(bytes(BODY_LEN - 1))


def test_unknown_header_raises():
    body = bytes([200]) + bytes(BODY_LEN - 1)
    with pytest.raises(ParseError):
        parse_body(body)


def test_find_packets_in_noisy_stream():
    good = build_body(PacketType.MESSAGE, b"node1 online")
    noise = bytes([0x00, 0xFF, 0x12]) * 5
    stream = noise + SYNC_WORD + good + noise + SYNC_WORD + good
    packets = find_packets(stream)
    assert len(packets) == 2
    assert all(p.text() == "node1 online" for p in packets)


def test_find_packets_skips_truncated_tail():
    good = build_body(PacketType.MESSAGE, b"full packet")
    truncated = SYNC_WORD + good[:20]  # sync word with no room for a full body
    stream = SYNC_WORD + good + truncated
    packets = find_packets(stream)
    assert len(packets) == 1


def test_payload_longer_than_max_rejected():
    with pytest.raises(ValueError):
        build_body(PacketType.MESSAGE, b"x" * 31)


def test_ack_and_invalid_types_parse():
    ack = parse_body(build_body(PacketType.ACK, b""))
    assert ack.packet_type is PacketType.ACK
    invalid = parse_body(build_body(PacketType.INVALID, b""))
    assert invalid.packet_type is PacketType.INVALID


def test_fuzzy_sync_tolerates_one_bit_error():
    good = build_body(PacketType.MESSAGE, b"noisy sync test")
    corrupted_sync = bytes([SYNC_WORD[0] ^ 0x01]) + SYNC_WORD[1:]  # 1 bit flipped
    stream = corrupted_sync + good

    assert find_packets(stream) == []  # exact match: nothing found
    packets = find_packets(stream, max_sync_bit_errors=1)
    assert len(packets) == 1
    assert packets[0].text() == "noisy sync test"


def test_fuzzy_sync_rejects_too_many_bit_errors():
    good = build_body(PacketType.MESSAGE, b"too corrupted")
    corrupted_sync = bytes([SYNC_WORD[0] ^ 0xFF]) + SYNC_WORD[1:]  # 8 bits flipped
    stream = corrupted_sync + good

    assert find_packets(stream, max_sync_bit_errors=2) == []


def test_fuzzy_sync_matches_exact_default_behavior_at_zero():
    good = build_body(PacketType.MESSAGE, b"exact still works")
    stream = SYNC_WORD + good
    assert find_packets(stream, max_sync_bit_errors=0) == find_packets(stream)
