"""Synthetic FFSK 1200/1800 signal generator, for self-testing nunu_decoder
without real hardware.

Mirrors nunu_decoder's four unvalidated PHY assumptions exactly (baud,
tone/bit polarity, bit order, direct tone-per-bit encoding) -- see that
module's docstring. This proves the encode/decode pair is internally
self-consistent, NOT that either side matches a real UV-K5. Bump this to
"validated" only once a real WAV capture with a known payload decodes
correctly (see tests/samples/, currently empty).
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

from nunu_decoder import BAUD, MARK_HZ, SAMPLE_RATE, SPACE_HZ
from nunu_parser import SYNC_WORD


def bytes_to_bits(data: bytes) -> list[int]:
    """Inverse of nunu_decoder.bits_to_bytes: MSB-first per byte."""
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def bits_to_audio(bits: list[int], fs: int = SAMPLE_RATE, baud: int = BAUD) -> np.ndarray:
    """Render a bit list as FFSK audio: bit 0 -> MARK_HZ, bit 1 -> SPACE_HZ.

    Each tone is phase-continuous within its own bit (a fresh sine
    starting at phase 0), which is the simplest possible encoder -- not
    necessarily what a real synthesizer chip does (continuous-phase FSK
    would carry phase across bit boundaries instead). Good enough for
    exercising the decoder's bit slicing; not a claim about real hardware.
    """
    samples_per_bit = fs / baud
    cursor = 0.0
    chunks = []
    for bit in bits:
        start = int(round(cursor))
        end = int(round(cursor + samples_per_bit))
        n = end - start
        freq = SPACE_HZ if bit else MARK_HZ
        t = np.arange(n) / fs
        chunks.append(np.sin(2 * np.pi * freq * t))
        cursor += samples_per_bit
    return np.concatenate(chunks).astype(np.float32)


def synthesize_packet(body: bytes, preamble_bytes: int = 4) -> np.ndarray:
    """Render one full NUNU frame (preamble + sync + body) as PCM audio.

    `body` must already be a valid 44-byte packet body -- use
    nunu_parser.build_body() to make one.
    """
    preamble = bytes([0x55, 0xAA] * preamble_bytes)[: preamble_bytes * 2]
    frame = preamble + SYNC_WORD + body
    bits = bytes_to_bits(frame)
    return bits_to_audio(bits)
