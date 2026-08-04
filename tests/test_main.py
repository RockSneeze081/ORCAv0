import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

import numpy as np
import pytest

import main
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
