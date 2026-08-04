import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

from nunu_decoder import decode
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


def test_decode_ignores_pure_noise():
    import numpy as np

    rng = np.random.default_rng(42)
    noise = (rng.standard_normal(44100) * 0.1).astype(np.float32)

    packets = decode(noise)

    assert packets == []


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
