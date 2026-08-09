import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

import numpy as np
import pytest

from nunu_decoder import MIN_FRAME_SAMPLES, decode
from nunu_parser import PacketType, build_body
from synth_nunu import synthesize_packet


def test_round_trip_plain_message():
    body = build_body(PacketType.MESSAGE, b"pota activation qrv")
    audio = synthesize_packet(body)

    packets = decode(audio)

    assert len(packets) == 1
    assert packets[0].packet_type is PacketType.MESSAGE
    assert packets[0].text() == "pota activation qrv"


def test_round_trip_two_packets_back_to_back():
    body1 = build_body(PacketType.MESSAGE, b"cq cq de ea3jhl")
    body2 = build_body(PacketType.ACK, b"")
    audio = synthesize_packet(body1)
    audio = audio.copy()
    import numpy as np

    silence = np.zeros(int(0.02 * 44100), dtype=np.float32)
    combined = np.concatenate([audio, silence, synthesize_packet(body2)])

    packets = decode(combined)

    assert len(packets) == 2
    assert packets[0].text() == "cq cq de ea3jhl"
    assert packets[1].packet_type is PacketType.ACK


def test_decode_skips_sync_match_with_truncated_body():
    """decode()'s own len(body_bits) != body_bit_len guard, not just
    nunu_parser's -- a sync word found too close to the end of the
    buffer to fit a full body must be skipped, not crash or return a
    bogus short packet.

    The overall buffer still has to clear MIN_FRAME_SAMPLES (a first
    version of this test didn't, and ended up exercising that early
    top-level guard instead of the one this test is actually about) --
    caught by checking coverage, not by the test merely passing. Leading
    silence pads total length past that floor while the *transmitted
    signal itself* -- sync word plus a truncated body -- still doesn't
    have enough bits remaining for a full body."""
    from nunu_parser import BODY_LEN, SYNC_WORD
    from synth_nunu import bits_to_audio, bytes_to_bits

    body = build_body(PacketType.MESSAGE, b"never fully arrives")
    frame = SYNC_WORD + body
    bits = bytes_to_bits(frame)
    full_audio = bits_to_audio(bits)

    # Cut off partway through the body -- sync word is intact and
    # findable, but there aren't enough samples left for BODY_LEN bytes.
    sync_bits = len(SYNC_WORD) * 8
    half_body_bits = (BODY_LEN * 8) // 2
    samples_per_bit = 44100 / 1200
    cutoff_sample = int((sync_bits + half_body_bits) * samples_per_bit)
    truncated_signal = full_audio[:cutoff_sample]

    leading_silence = np.zeros(MIN_FRAME_SAMPLES, dtype=np.float32)
    truncated_audio = np.concatenate([leading_silence, truncated_signal])
    assert len(truncated_audio) >= MIN_FRAME_SAMPLES

    assert decode(truncated_audio) == []


def test_decode_skips_sync_match_with_bad_header_byte():
    """decode()'s own except ParseError: continue, not just
    nunu_parser's -- a bit-perfect sync match whose body has an unknown
    header byte must be skipped, not crash or propagate the ParseError."""
    from nunu_parser import BODY_LEN, NONCE_LEN, PAYLOAD_LEN
    from synth_nunu import synthesize_packet

    bad_body = bytes([200]) + bytes(PAYLOAD_LEN) + bytes(NONCE_LEN)  # 200 isn't a PacketType
    assert len(bad_body) == BODY_LEN
    audio = synthesize_packet(bad_body)

    assert decode(audio) == []


def test_decode_ignores_pure_noise():
    import numpy as np

    rng = np.random.default_rng(42)
    noise = (rng.standard_normal(44100) * 0.1).astype(np.float32)

    packets = decode(noise)

    assert packets == []


@pytest.mark.parametrize(
    "n_samples",
    [0, 1, 10, 26, MIN_FRAME_SAMPLES - 1],
)
def test_decode_returns_empty_for_buffer_too_short_for_one_frame(n_samples):
    """Regression test: scipy's sosfiltfilt raises ValueError on an input
    shorter than its padlen (~27 samples for the current filter) -- which
    includes the empty-buffer case. A truncated or empty WAV file is a
    normal thing for run_offline to be handed, not exceptional, so this
    must return [] rather than propagate a crash."""
    audio = np.zeros(n_samples, dtype=np.float32)

    assert decode(audio) == []


def test_decode_handles_nan_and_inf_without_crashing():
    """Not a normal WAV, but scipy's filter doesn't raise on non-finite
    input either -- garbage in, empty result out, not a crash."""
    assert decode(np.full(44100, np.nan, dtype=np.float32)) == []
    assert decode(np.full(44100, np.inf, dtype=np.float32)) == []


def test_decode_recovers_clock_at_arbitrary_start_offset():
    """The actual point of phase search: a real capture won't hand the
    decoder audio that starts exactly on a bit boundary. Prepend an
    offset that is NOT a multiple of the ~36.75-sample bit period and
    confirm decode() still finds the packet."""
    import numpy as np

    body = build_body(PacketType.MESSAGE, b"clock recovery test")
    packet_audio = synthesize_packet(body)

    for leading_samples in (1, 5, 13, 20, 30, 50, 137):
        prefix = np.zeros(leading_samples, dtype=np.float32)
        audio = np.concatenate([prefix, packet_audio])

        packets = decode(audio)

        assert len(packets) == 1, f"failed at leading_samples={leading_samples}"
        assert packets[0].text() == "clock recovery test"


def test_decode_finds_packet_in_realistic_multi_second_capture():
    """Closer to the real Phase-1 use case than the other tests: a several
    -second buffer with noise before and after the packet, at a position
    the decoder has to find rather than one handed to it at the start."""
    import numpy as np

    body = build_body(PacketType.MESSAGE, b"timing test message")
    packet_audio = synthesize_packet(body)
    rng = np.random.default_rng(3)
    pre = (rng.standard_normal(int(1.7 * 44100)) * 0.05).astype(np.float32)
    post = (rng.standard_normal(int(2.9 * 44100)) * 0.05).astype(np.float32)
    audio = np.concatenate([pre, packet_audio, post])

    packets = decode(audio)

    assert len(packets) == 1
    assert packets[0].text() == "timing test message"


def test_round_trip_survives_moderate_noise():
    """Regression guard, not a claim about real-world SNR margin -- the
    real margin can only come from a real capture. Signal amplitude is
    +-1; noise_std=0.2 decodes cleanly, 0.5 does not (checked by hand)."""
    import numpy as np

    body = build_body(PacketType.MESSAGE, b"pota activation qrv")
    audio = synthesize_packet(body)
    rng = np.random.default_rng(7)
    noisy = audio + rng.standard_normal(len(audio)).astype(np.float32) * 0.2

    packets = decode(noisy)

    assert len(packets) == 1
    assert packets[0].text() == "pota activation qrv"
