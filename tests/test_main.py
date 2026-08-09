import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge"))

import numpy as np
import pytest

import main
from mesh_bridge import BROADCAST_ADDR
from nunu_parser import NunuPacket, PacketType, build_body
from synth_nunu import synthesize_packet


class FakeInterface:
    def __init__(self):
        self.sent = []

    def sendText(self, text, destinationId):
        self.sent.append((text, destinationId))


def _packet(packet_type=PacketType.MESSAGE, payload=b"hello", nonce=bytes(13)):
    return NunuPacket(packet_type=packet_type, payload=payload.ljust(30, b"\x00"), nonce=nonce)


def test_packet_fingerprint_deterministic():
    p1 = _packet(payload=b"same content")
    p2 = _packet(payload=b"same content")
    assert main._packet_fingerprint(p1) == main._packet_fingerprint(p2)


def test_packet_fingerprint_differs_by_content():
    p1 = _packet(payload=b"message a")
    p2 = _packet(payload=b"message b")
    assert main._packet_fingerprint(p1) != main._packet_fingerprint(p2)


def test_route_packet_drops_encrypted():
    packet = _packet(packet_type=PacketType.ENCRYPTED_MESSAGE, payload=b"ciphertext-ish")
    iface = FakeInterface()
    main.route_packet(packet, iface, aliases={})
    assert iface.sent == []


@pytest.mark.parametrize("packet_type", [PacketType.ACK, PacketType.INVALID])
def test_route_packet_drops_ack_and_invalid(packet_type):
    packet = _packet(packet_type=packet_type, payload=b"")
    iface = FakeInterface()
    main.route_packet(packet, iface, aliases={})
    assert iface.sent == []


def test_route_packet_routes_plain_message():
    packet = _packet(payload=b"@ea3jhl summit activated")
    iface = FakeInterface()
    main.route_packet(packet, iface, aliases={"ea3jhl": "!a1b2c3d4"})
    assert iface.sent == [("summit activated", "!a1b2c3d4")]


def test_build_interface_dry_run_returns_dry_run_interface():
    iface = main.build_interface(dry_run=True, connection=None)
    assert isinstance(iface, main.DryRunInterface)


def _write_synthetic_wav(path: Path, text: str) -> None:
    from scipy.io.wavfile import write as write_wav

    body = build_body(PacketType.MESSAGE, text.encode("ascii"))
    audio = synthesize_packet(body)
    audio_int16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    write_wav(str(path), 44100, audio_int16)


def test_run_offline_decodes_and_routes(tmp_path):
    wav_path = tmp_path / "capture.wav"
    _write_synthetic_wav(wav_path, "@ea3jhl pota s5 activated")
    iface = FakeInterface()

    count = main.run_offline(wav_path, iface, aliases={"ea3jhl": "!a1b2c3d4"})

    assert count == 1
    assert iface.sent == [("pota s5 activated", "!a1b2c3d4")]


def test_run_offline_handles_stereo_wav(tmp_path):
    """run_offline's `if audio.ndim > 1: audio = audio[:, 0]` -- every
    other run_offline test is mono."""
    from scipy.io.wavfile import write as write_wav

    body = build_body(PacketType.MESSAGE, b"stereo offline test")
    mono = synthesize_packet(body)
    stereo_int16 = (np.clip(np.column_stack([mono, mono]), -1, 1) * 32767).astype(np.int16)
    wav_path = tmp_path / "stereo.wav"
    write_wav(str(wav_path), 44100, stereo_int16)
    iface = FakeInterface()

    count = main.run_offline(wav_path, iface, aliases={})

    assert count == 1
    assert iface.sent == [("stereo offline test", BROADCAST_ADDR)]


def test_run_offline_handles_float32_wav(tmp_path):
    """run_offline's else branch for non-integer dtype -- every other
    run_offline test writes int16 PCM."""
    from scipy.io.wavfile import write as write_wav

    body = build_body(PacketType.MESSAGE, b"float32 offline test")
    audio = np.clip(synthesize_packet(body), -1.0, 1.0)
    wav_path = tmp_path / "float.wav"
    write_wav(str(wav_path), 44100, audio)
    iface = FakeInterface()

    count = main.run_offline(wav_path, iface, aliases={})

    assert count == 1
    assert iface.sent == [("float32 offline test", BROADCAST_ADDR)]


def test_run_offline_no_packets_in_pure_noise(tmp_path):
    from scipy.io.wavfile import write as write_wav

    wav_path = tmp_path / "noise.wav"
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(44100) * 0.1 * 32767).astype(np.int16)
    write_wav(str(wav_path), 44100, noise)
    iface = FakeInterface()

    count = main.run_offline(wav_path, iface, aliases={})

    assert count == 0
    assert iface.sent == []


def test_run_offline_does_not_crash_on_truncated_wav(tmp_path):
    """Regression test: a WAV with only a handful of samples used to
    crash decode() (scipy's filter needs a minimum length); a truncated
    download or an accidentally-empty file is a normal thing to hand
    --input, not an exceptional one."""
    from scipy.io.wavfile import write as write_wav

    wav_path = tmp_path / "truncated.wav"
    write_wav(str(wav_path), 44100, np.zeros(5, dtype=np.int16))
    iface = FakeInterface()

    count = main.run_offline(wav_path, iface, aliases={})

    assert count == 0
    assert iface.sent == []


def test_run_offline_missing_file_raises_runtime_error(tmp_path):
    with pytest.raises(RuntimeError, match="couldn't read"):
        main.run_offline(tmp_path / "does_not_exist.wav", FakeInterface(), aliases={})


def test_run_offline_non_wav_file_raises_runtime_error(tmp_path):
    not_a_wav = tmp_path / "not_a_wav.wav"
    not_a_wav.write_text("this is definitely not a WAV file")

    with pytest.raises(RuntimeError, match="couldn't read"):
        main.run_offline(not_a_wav, FakeInterface(), aliases={})


def test_main_missing_input_file_exits_cleanly_not_a_traceback(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        sys, "argv", ["main.py", "--input", str(tmp_path / "ghost.wav"), "--dry-run"]
    )

    exit_code = main.main()

    assert exit_code == 1
    assert "couldn't read" in caplog.text


def test_main_requires_meshtastic_unless_dry_run(monkeypatch, tmp_path, capsys):
    wav_path = tmp_path / "x.wav"
    _write_synthetic_wav(wav_path, "irrelevant")
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(wav_path)])

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 2
    assert "--meshtastic is required" in capsys.readouterr().err


def test_main_dry_run_offline_end_to_end(monkeypatch, tmp_path, capsys):
    wav_path = tmp_path / "capture.wav"
    _write_synthetic_wav(wav_path, "cq cq de ea3jhl")
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(wav_path), "--dry-run"])

    exit_code = main.main()

    assert exit_code == 0
    assert "cq cq de ea3jhl" in capsys.readouterr().out


def test_append_to_buffer_keeps_everything_under_limit():
    buffer = np.array([1.0, 2.0], dtype=np.float32)
    result = main._append_to_buffer(buffer, np.array([3.0, 4.0], dtype=np.float32), max_samples=10)
    np.testing.assert_array_equal(result, [1.0, 2.0, 3.0, 4.0])


def test_append_to_buffer_trims_oldest_samples_first():
    buffer = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    result = main._append_to_buffer(buffer, np.array([4.0, 5.0], dtype=np.float32), max_samples=4)
    np.testing.assert_array_equal(result, [2.0, 3.0, 4.0, 5.0])


def _wav_audio(text: str) -> np.ndarray:
    body = build_body(PacketType.MESSAGE, text.encode("ascii"))
    return synthesize_packet(body)


def test_drain_and_route_routes_new_packet():
    buffer = _wav_audio("cq cq de ea3jhl")
    iface = FakeInterface()
    seen = {}

    routed = main._drain_and_route(buffer, seen, now=1000.0, seen_ttl=10.0, interface=iface, aliases={})

    assert routed == 1
    assert iface.sent == [("cq cq de ea3jhl", BROADCAST_ADDR)]
    assert len(seen) == 1


def test_drain_and_route_does_not_reroute_within_ttl():
    buffer = _wav_audio("repeated message")
    iface = FakeInterface()
    seen = {}
    main._drain_and_route(buffer, seen, now=1000.0, seen_ttl=10.0, interface=iface, aliases={})

    routed_again = main._drain_and_route(
        buffer, seen, now=1005.0, seen_ttl=10.0, interface=iface, aliases={}
    )

    assert routed_again == 0
    assert len(iface.sent) == 1  # still just the one send from the first pass


def test_drain_and_route_reroutes_after_ttl_expires():
    buffer = _wav_audio("repeated message")
    iface = FakeInterface()
    seen = {}
    main._drain_and_route(buffer, seen, now=1000.0, seen_ttl=10.0, interface=iface, aliases={})

    routed_later = main._drain_and_route(
        buffer, seen, now=1011.0, seen_ttl=10.0, interface=iface, aliases={}
    )

    assert routed_later == 1
    assert len(iface.sent) == 2


def test_drain_and_route_returns_zero_for_silence():
    buffer = np.zeros(44100, dtype=np.float32)
    iface = FakeInterface()

    routed = main._drain_and_route(buffer, {}, now=1000.0, seen_ttl=10.0, interface=iface, aliases={})

    assert routed == 0
    assert iface.sent == []


def test_main_list_devices(monkeypatch, capsys):
    fake_devices = [{"name": "Fake Mic", "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 44100.0}]
    monkeypatch.setattr(sys, "argv", ["main.py", "--list-devices"])
    monkeypatch.setattr("sounddevice.query_devices", lambda: fake_devices)

    exit_code = main.main()

    assert exit_code == 0
    assert "Fake Mic" in capsys.readouterr().out


def test_main_closes_interface_when_not_dry_run(monkeypatch, tmp_path):
    """The finally block's `if not args.dry_run and hasattr(interface,
    "close"): interface.close()` -- every other main() test uses
    --dry-run, where this is a deliberate no-op (DryRunInterface has no
    real connection to release). Patches build_interface rather than
    actually connecting to hardware."""

    class FakeRealInterface:
        def __init__(self):
            self.closed = False

        def sendText(self, text, destinationId):
            pass

        def close(self):
            self.closed = True

    fake_interface = FakeRealInterface()
    wav_path = tmp_path / "x.wav"
    _write_synthetic_wav(wav_path, "irrelevant")
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(wav_path), "--meshtastic", "/dev/fake"])
    monkeypatch.setattr(main, "build_interface", lambda dry_run, connection: fake_interface)

    exit_code = main.main()

    assert exit_code == 0
    assert fake_interface.closed is True
