#!/usr/bin/env python3
"""NUNU packet parser.

Parses the 44-byte NUNU data body (header + payload + nonce) that follows
the sync word. See AGENTS.md "Protocol: NUNU Packet" for the layout —
verified against the actual firmware source (app/messenger.c in
kamilsss655/uv-k5-firmware-custom), not the wiki. There is no CRC on the
wire: the BK4819's hardware CRC is disabled for messenger packets and the
firmware's software CRC driver is never invoked for them. Sync-word match
+ correct body length is the only framing check available.
"""

from dataclasses import dataclass
from enum import IntEnum

SYNC_WORD = bytes.fromhex("3072576c")

HEADER_LEN = 1
PAYLOAD_LEN = 30
NONCE_LEN = 13
BODY_LEN = HEADER_LEN + PAYLOAD_LEN + NONCE_LEN  # 44


class PacketType(IntEnum):
    """Mirrors enum PacketType in app/messenger.h."""

    MESSAGE = 100
    ENCRYPTED_MESSAGE = 101
    ACK = 102
    INVALID = 103


class ParseError(ValueError):
    pass


@dataclass
class NunuPacket:
    packet_type: PacketType
    payload: bytes
    nonce: bytes

    @property
    def is_encrypted(self) -> bool:
        return self.packet_type is PacketType.ENCRYPTED_MESSAGE

    def text(self) -> str:
        """Decode the payload as text, trimming zero padding.

        Only meaningful for PacketType.MESSAGE. Encrypted payloads need
        ChaCha20 decryption first (not implemented here — RRAE means ORCA
        itself must never transmit encrypted packets, but it may still
        receive them from other NUNU nodes and should not crash on one).
        """
        return self.payload.rstrip(b"\x00").decode("ascii", errors="replace")


def parse_body(body: bytes) -> NunuPacket:
    """Parse a 44-byte NUNU packet body (everything after the sync word).

    Raises ParseError if the length is wrong or the header byte isn't a
    known PacketType — there's no CRC to lean on, so this is the only
    validation available.
    """
    if len(body) != BODY_LEN:
        raise ParseError(f"expected {BODY_LEN}-byte body, got {len(body)}")

    try:
        packet_type = PacketType(body[0])
    except ValueError as exc:
        raise ParseError(f"unknown header byte: {body[0]}") from exc

    payload = body[HEADER_LEN : HEADER_LEN + PAYLOAD_LEN]
    nonce = body[HEADER_LEN + PAYLOAD_LEN :]

    return NunuPacket(packet_type=packet_type, payload=payload, nonce=nonce)


def _hamming_distance(a: bytes, b: bytes) -> int:
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


def find_sync_positions(stream: bytes, max_sync_bit_errors: int = 0) -> list[int]:
    """Return byte offsets where the sync word starts in `stream`.

    max_sync_bit_errors: tolerate up to this many bit errors (Hamming
    distance) in the 32-bit sync word. 0 (default) requires an exact
    match and uses a fast substring search; >0 falls back to a
    byte-by-byte Hamming scan, since real audio can flip an occasional
    bit even where symbol timing is otherwise correct -- an
    exact-match-only search has zero margin for that.

    After a match at `idx`, the scan resumes at idx + len(SYNC_WORD) --
    i.e. it doesn't skip the body region, matching the original
    exact-match behavior. A body that happens to contain 4 bytes close
    to SYNC_WORD could in principle produce a spurious extra position;
    not handled here, out of scope for this pass.
    """
    if max_sync_bit_errors <= 0:
        positions = []
        pos = 0
        while True:
            idx = stream.find(SYNC_WORD, pos)
            if idx == -1:
                break
            positions.append(idx)
            pos = idx + len(SYNC_WORD)
        return positions

    sync_len = len(SYNC_WORD)
    positions = []
    idx = 0
    skip_until = -1
    while idx <= len(stream) - sync_len:
        if idx < skip_until:
            idx += 1
            continue
        if _hamming_distance(stream[idx : idx + sync_len], SYNC_WORD) <= max_sync_bit_errors:
            positions.append(idx)
            skip_until = idx + sync_len
        idx += 1
    return positions


def find_packets(stream: bytes, max_sync_bit_errors: int = 0) -> list[NunuPacket]:
    """Scan a byte stream for sync-word-delimited packets.

    Bodies that fail to parse (bad header, truncated tail) are skipped
    rather than raised, since a decoded stream can have noise around real
    packets — one bad packet shouldn't drop the rest. See
    find_sync_positions for max_sync_bit_errors.
    """
    packets = []
    for idx in find_sync_positions(stream, max_sync_bit_errors):
        body_start = idx + len(SYNC_WORD)
        body = stream[body_start : body_start + BODY_LEN]
        if len(body) == BODY_LEN:
            try:
                packets.append(parse_body(body))
            except ParseError:
                pass
    return packets


def build_body(
    packet_type: PacketType, payload: bytes, nonce: bytes = bytes(NONCE_LEN)
) -> bytes:
    """Inverse of parse_body — mainly for tests and for TX support later."""
    if len(payload) > PAYLOAD_LEN:
        raise ValueError(f"payload longer than {PAYLOAD_LEN} bytes")
    if len(nonce) != NONCE_LEN:
        raise ValueError(f"nonce must be {NONCE_LEN} bytes")
    padded_payload = payload.ljust(PAYLOAD_LEN, b"\x00")
    return bytes([packet_type]) + padded_payload + nonce
