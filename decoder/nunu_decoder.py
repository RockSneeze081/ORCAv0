#!/usr/bin/env python3
"""NUNU FSK-over-FM decoder.

Demodulates the BK4819 MOD_AFSK_1200 signal ("FFSK 1200/1800", the "for
good conditions" mode) from a PCM capture into NUNU packet bytes, then
hands framing off to nunu_parser. This is the only one of the firmware's
three modulation modes that's real audible dual-tone AFSK rather than
direct baseband FM (see app/messenger.c: MOD_FSK_450/700 configure
BK4819_REG_58 for "no tones, direct FM"; only MOD_AFSK_1200 selects
"FFSK 1200/1800"), which is what makes Goertzel/zero-crossing decoding
from a soundcard capture possible at all -- so it's the assumed target
here. If the actual link uses MOD_FSK_450/700 this module doesn't apply.

--- Working assumptions, NOT validated against real hardware ---
The firmware only configures the BK4819's *internal* FFSK modem; it never
says how bits map to tones once they leave the chip as audio, because the
chip doesn't need that mapping to be known in software. These four have
zero source backing and are the first things to check against a real
capture (see tests/synth_nunu.py for the synthetic self-test that stands
in for one):
  1. Baud rate: 1200 bps, inferred purely from the "FFSK 1200" name.
  2. Tone/bit polarity: 1200 Hz = bit 0, 1800 Hz = bit 1 (arbitrary).
  3. Bit order: MSB-first within each byte (arbitrary).
  4. Direct tone-per-bit encoding, NOT NRZI (unverified either way).

--- Clock recovery ---
decode() doesn't know where in the buffer a packet's bit-0 actually
starts, and this decoder is surprisingly phase-sensitive: measured
against a synthetic packet, sync-word detection survives a timing error
of about +/-3 samples out of a ~37-sample bit period and then collapses
sharply (bit accuracy falls from 97% to ~50%, i.e. noise) rather than
degrading gracefully -- once a window straddles two symbols close to
evenly, "the dominant tone" stops meaning anything. There's no real
Gardner/Mueller-and-Muller timing-error-detector loop here; instead
decode() brute-forces PHASE_SEARCH_STEPS starting offsets spanning one
bit period and demodulates the whole buffer at each. Correct in spirit
(independent bursts in one capture can each need a different phase) but
not efficient -- fine at Phase-1 scale (seconds of audio, offline), would
need real timing recovery before it could run continuously on embedded
hardware (Phase 2).

Sync search happens in bit-space (_find_sync_bit_positions), not after
packing into bytes: an arbitrary amount of leading silence/noise before
a packet means bit 0 of the demodulated stream lands on a true 8-bit
byte boundary of the original transmission only by a 1-in-8 coincidence,
so byte-aligned search would miss most real packets even with perfect
sample timing. Byte alignment instead falls out of *where the sync word
is found*: the 44-byte body is packed starting exactly sync_bit_len bits
after that match, wherever it landed.

Different phases can each find "the same" real packet, and on a noisy
signal they don't necessarily agree bit-for-bit past the sync word
(different phases sample different parts of the same noise) -- so
results aren't deduped by content. Each candidate is scored by its
average per-bit confidence (see demodulate_bits), candidates within one
bit period of each other are treated as one underlying packet, and only
the highest-confidence one per group survives into the output.
"""

from typing import Iterator

import numpy as np
from scipy.signal import butter, sosfiltfilt

from nunu_parser import BODY_LEN, SYNC_WORD, NunuPacket, ParseError, parse_body

SAMPLE_RATE = 44100
BAUD = 1200  # ASSUMPTION 1
MARK_HZ = 1200  # bit 0, ASSUMPTION 2
SPACE_HZ = 1800  # bit 1
SAMPLES_PER_BIT = SAMPLE_RATE / BAUD  # 36.75 -- non-integer, see _bit_windows

# Empirically, sync detection holds for roughly +-3 samples out of ~37 (see
# module docstring) -- 8 evenly spaced candidates give each a good chance of
# landing within that window without the search cost exploding.
PHASE_SEARCH_STEPS = 8

# Sync word fuzzy-match tolerance (bit-level Hamming distance) for the
# multi-phase search below. 0 (exact match) by default -- kept
# conservative mainly to bound how much _find_sync_bit_positions has to
# check (every bit offset already, no point widening the match target
# too). Now that candidates are scored by confidence and grouped by
# position rather than deduped by exact content, a small tolerance
# (1-2) should be safe to enable for a noisier real signal; untested
# either way without real captures, so left at the conservative default.
SYNC_BIT_ERROR_TOLERANCE = 0


def _goertzel_power(samples: np.ndarray, freq: float, fs: int) -> float:
    """Goertzel power of `samples` at exactly `freq` Hz.

    Deliberately does NOT round to the nearest FFT-style bin (k = n*freq/fs
    rounded to an int): at ~37 samples/bit, fs/n is ~1200 Hz of bin
    spacing, coarser than the 600 Hz gap between the mark and space
    tones -- both would round to the same bin and become indistinguishable.
    Since the two candidate frequencies are known exactly rather than
    discovered, Goertzel can and should be evaluated at the true
    frequency directly; that's a valid use of the recursion, just not the
    "equivalent to one FFT bin" special case.
    """
    n = len(samples)
    if n == 0:
        return 0.0
    omega = 2 * np.pi * freq / fs
    coeff = 2 * np.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for x in samples:
        s = x + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    return s_prev2**2 + s_prev**2 - coeff * s_prev * s_prev2


def _bandpass(audio: np.ndarray, fs: int) -> np.ndarray:
    """Reject far out-of-band noise (rumble, hiss) without smearing the tones.

    A passband tight around the two tones (e.g. 840-2340 Hz) sounded
    like the right idea but rings badly at bit boundaries: every bit
    period (~37 samples) is a fresh phase-0 tone, i.e. an amplitude/phase
    discontinuity, and a narrow filter's impulse response is long enough
    relative to that period to bleed energy into neighboring bits and
    flip the tone comparison. Measured against tests/synth_nunu.py: a
    tight 4th-order band corrupted ~11% of bits (400/448 correct); this
    wider, still-4th-order band recovers 448/448.
    """
    sos = butter(4, [500, 4000], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, audio)


def _bit_windows(n_samples: int, phase_offset: int = 0) -> Iterator[tuple[int, int]]:
    """Yield integer (start, end) sample bounds for each bit period.

    SAMPLES_PER_BIT is fractional, so a fixed-integer window would drift
    by more than a full bit across a 44-byte body (352 bits * ~0.25
    sample rounding error > one bit period). Tracking a float cursor and
    rounding each edge independently keeps drift bounded to +/-0.5
    sample instead of compounding.

    phase_offset shifts where bit 0's window starts -- see decode() for
    why: the real start of a packet's bit clock within the buffer isn't
    known in advance. A nonzero offset eats into how much fits at the
    tail end too, so the last window is clipped to n_samples rather than
    dropped outright when it would otherwise run past the end -- a body
    that's already right at the edge of the buffer shouldn't lose its
    final byte just because phase search shifted everything by a few
    samples (Goertzel doesn't need a fixed-length window to work).
    """
    cursor = float(phase_offset)
    while True:
        start = int(round(cursor))
        if start >= n_samples:
            return
        end = min(int(round(cursor + SAMPLES_PER_BIT)), n_samples)
        yield start, end
        cursor += SAMPLES_PER_BIT


def demodulate_bits(
    audio: np.ndarray, fs: int = SAMPLE_RATE, phase_offset: int = 0, prefiltered: bool = False
) -> tuple[list[int], list[float]]:
    """FFSK-demodulate a PCM buffer into (bits, per-bit confidence).

    confidence[i] is the normalized power margin between the two tones
    for bit i, in [0, 1]: ~0 means mark/space were nearly tied (the
    window likely straddled a symbol boundary or was mostly noise), ~1
    means one tone clearly dominated. decode() uses this to pick between
    candidate packets found at different phase offsets, since sync-word
    match alone doesn't say how trustworthy the *rest* of a packet's
    bits are.

    Pass prefiltered=True if `audio` has already been through _bandpass
    (decode()'s phase search reuses one filter pass across all phases
    instead of re-filtering the same audio once per candidate).
    """
    filtered = audio if prefiltered else _bandpass(audio, fs)
    bits = []
    confidences = []
    for start, end in _bit_windows(len(filtered), phase_offset):
        window = filtered[start:end]
        mark_power = _goertzel_power(window, MARK_HZ, fs)
        space_power = _goertzel_power(window, SPACE_HZ, fs)
        bits.append(1 if space_power > mark_power else 0)
        total = mark_power + space_power
        confidences.append(abs(space_power - mark_power) / total if total > 0 else 0.0)
    return bits, confidences


def bits_to_bytes(bits: list[int]) -> bytes:
    """Pack bits MSB-first into bytes (ASSUMPTION 3); drops a short tail."""
    n_bytes = len(bits) // 8
    out = bytearray(n_bytes)
    for i in range(n_bytes):
        byte = 0
        for bit in bits[i * 8 : (i + 1) * 8]:
            byte = (byte << 1) | bit
        out[i] = byte
    return bytes(out)


def _bytes_to_bits(data: bytes) -> list[int]:
    """Inverse of bits_to_bytes: MSB-first per byte."""
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


_SYNC_BITS = _bytes_to_bits(SYNC_WORD)


def _find_sync_bit_positions(bits: list[int], max_bit_errors: int) -> list[int]:
    """Bit-level sync search: check every bit offset, not just every 8th.

    Packing demodulated bits into bytes and then searching for the
    sync word (nunu_parser.find_sync_positions) only works if bit 0 of
    the demodulated stream happens to land on a true byte boundary of
    the original transmission. With an arbitrary amount of leading
    silence/noise before a packet -- the normal case for a real capture
    -- that's about a 1-in-8 coincidence, not something to rely on. This
    searches in bit-space directly, so byte alignment falls out of
    *where the sync word is found* rather than being assumed up front.
    """
    positions = []
    n = len(bits)
    sync_len = len(_SYNC_BITS)
    for start in range(0, n - sync_len + 1):
        errors = sum(1 for a, b in zip(bits[start : start + sync_len], _SYNC_BITS) if a != b)
        if errors <= max_bit_errors:
            positions.append(start)
    return positions


def decode(
    audio: np.ndarray,
    fs: int = SAMPLE_RATE,
    phase_search_steps: int = PHASE_SEARCH_STEPS,
    sync_bit_error_tolerance: int = SYNC_BIT_ERROR_TOLERANCE,
) -> list[NunuPacket]:
    """PCM buffer -> parsed NunuPacket list.

    Since bit-0's true sample offset is unknown (see module docstring:
    "Clock recovery"), this demodulates the whole buffer once per
    candidate phase offset -- brute-force, but linear in buffer length.

    Multiple phases routinely find "the same" real packet, and on a
    noisy signal they don't always agree bit-for-bit past the sync word
    (different phases sample different parts of the same noise). So
    candidates aren't deduped by content: each is scored by its average
    per-bit confidence (demodulate_bits), candidates whose estimated
    start position falls within one bit period of each other are treated
    as the same underlying packet, and only the highest-confidence one
    in each group is kept.
    """
    filtered = _bandpass(audio, fs)
    step = SAMPLES_PER_BIT / phase_search_steps
    sync_bit_len = len(_SYNC_BITS)
    body_bit_len = BODY_LEN * 8

    candidates = []  # (approx_start_sample, confidence, packet)
    for i in range(phase_search_steps):
        phase_offset = round(i * step)
        bits, confidences = demodulate_bits(filtered, fs, phase_offset=phase_offset, prefiltered=True)
        for sync_bit_pos in _find_sync_bit_positions(bits, sync_bit_error_tolerance):
            body_bits_start = sync_bit_pos + sync_bit_len
            body_bits = bits[body_bits_start : body_bits_start + body_bit_len]
            if len(body_bits) != body_bit_len:
                continue
            try:
                packet = parse_body(bits_to_bytes(body_bits))
            except ParseError:
                continue
            conf_span = confidences[sync_bit_pos : body_bits_start + body_bit_len]
            confidence = sum(conf_span) / len(conf_span)
            approx_start = phase_offset + sync_bit_pos * SAMPLES_PER_BIT
            candidates.append((approx_start, confidence, packet))

    candidates.sort(key=lambda c: c[0])
    packets: list[NunuPacket] = []
    group: list[tuple[float, float, NunuPacket]] = []

    def flush_group():
        if group:
            packets.append(max(group, key=lambda c: c[1])[2])

    for candidate in candidates:
        if group and candidate[0] - group[-1][0] > SAMPLES_PER_BIT:
            flush_group()
            group = []
        group.append(candidate)
    flush_group()

    return packets
