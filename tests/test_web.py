import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

import numpy as np
import pytest
from scipy.io.wavfile import write as write_wav

import web
from mesh_bridge import save_aliases
from nunu_parser import PacketType, build_body
from synth_nunu import synthesize_packet


@pytest.fixture
def client(tmp_path):
    web.app.config["ALIAS_STORE_PATH"] = tmp_path / "alias_store.json"
    web.app.config["TESTING"] = True
    with web.app.test_client() as c:
        yield c


def _wav_bytes(text: str) -> bytes:
    body = build_body(PacketType.MESSAGE, text.encode("ascii"))
    audio = synthesize_packet(body)
    audio_int16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    write_wav(buf, 44100, audio_int16)
    buf.seek(0)
    return buf.read()


def test_index_get_no_aliases(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"No aliases" in resp.data


def test_index_get_shows_aliases(client, tmp_path):
    save_aliases({"ea3jhl": "!a1b2c3d4"}, tmp_path / "alias_store.json")

    resp = client.get("/")

    assert b"ea3jhl" in resp.data
    assert b"!a1b2c3d4" in resp.data


def test_upload_without_file_shows_error(client):
    resp = client.post("/", data={}, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"choose a WAV file" in resp.data


def test_upload_non_wav_file_shows_error_not_500(client):
    """decode_upload()'s failure path -- unlike main.run_offline, it has
    no RuntimeError wrapping of its own; the view's `except Exception`
    is what's supposed to catch scipy failing to parse garbage as a WAV
    and turn it into a page message instead of a 500."""
    garbage = io.BytesIO(b"this is not a wav file, just some bytes")

    resp = client.post(
        "/", data={"wav": (garbage, "not_really.wav")}, content_type="multipart/form-data"
    )

    assert resp.status_code == 200
    assert b"Error:" in resp.data


def test_upload_broadcast_message_routes_ok(client):
    wav = _wav_bytes("cq cq de ea3jhl")

    resp = client.post(
        "/",
        data={"wav": (io.BytesIO(wav), "capture.wav")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    assert b"1 packet(s) found" in resp.data
    assert b"cq cq de ea3jhl" in resp.data
    assert b"-&gt; ^all" in resp.data or b"-> ^all" in resp.data


def test_upload_html_in_payload_is_escaped_not_injected(client):
    """NUNU payload text is attacker-controlled -- it's whatever the
    transmitting radio sent. Confirms Flask/Jinja's default autoescaping
    actually applies here (render_template_string uses the app's Jinja
    env, which escapes by default) rather than assuming it does; a
    payload containing markup must not appear as live HTML in the
    response, or displaying decoded packets would be a stored-XSS vector."""
    wav = _wav_bytes("<script>alert(1)</script>")

    resp = client.post(
        "/",
        data={"wav": (io.BytesIO(wav), "capture.wav")},
        content_type="multipart/form-data",
    )

    assert b"<script>alert(1)</script>" not in resp.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in resp.data


def test_upload_unknown_alias_shows_dropped(client):
    wav = _wav_bytes("@ghost hello")

    resp = client.post(
        "/",
        data={"wav": (io.BytesIO(wav), "capture.wav")},
        content_type="multipart/form-data",
    )

    assert b"dropped: unknown alias" in resp.data


def test_upload_known_alias_shows_destination(client, tmp_path):
    save_aliases({"ea3jhl": "!a1b2c3d4"}, tmp_path / "alias_store.json")
    wav = _wav_bytes("@ea3jhl pota activated")

    resp = client.post(
        "/",
        data={"wav": (io.BytesIO(wav), "capture.wav")},
        content_type="multipart/form-data",
    )

    assert b"!a1b2c3d4" in resp.data
    assert b"pota activated" in resp.data


def test_upload_noise_finds_no_packets(client):
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(44100) * 0.1 * 32767).astype(np.int16)
    buf = io.BytesIO()
    write_wav(buf, 44100, noise)
    buf.seek(0)

    resp = client.post(
        "/",
        data={"wav": (buf, "noise.wav")},
        content_type="multipart/form-data",
    )

    assert b"0 packet(s) found" in resp.data


def test_upload_stereo_wav_uses_first_channel(client):
    """_load_wav_as_float32's `if audio.ndim > 1: audio = audio[:, 0]` --
    every other upload test is mono. Duplicates the mono signal into two
    channels rather than asserting anything about channel-specific
    content, since the decoder only ever sees channel 0 either way."""
    body = build_body(PacketType.MESSAGE, b"stereo capture")
    mono = synthesize_packet(body)
    stereo = np.column_stack([mono, mono])
    stereo_int16 = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    write_wav(buf, 44100, stereo_int16)
    buf.seek(0)

    resp = client.post(
        "/", data={"wav": (buf, "stereo.wav")}, content_type="multipart/form-data"
    )

    assert b"1 packet(s) found" in resp.data
    assert b"stereo capture" in resp.data


def test_upload_float32_wav(client):
    """_load_wav_as_float32's else branch (non-integer dtype) -- every
    other upload test writes int16 PCM, the format capture.py actually
    produces, but scipy can also read float32 WAVs and this function
    claims to handle that case too."""
    body = build_body(PacketType.MESSAGE, b"float32 capture")
    audio = np.clip(synthesize_packet(body), -1.0, 1.0)
    buf = io.BytesIO()
    write_wav(buf, 44100, audio)  # float32 array -> scipy writes IEEE float WAV
    buf.seek(0)

    resp = client.post(
        "/", data={"wav": (buf, "float.wav")}, content_type="multipart/form-data"
    )

    assert b"1 packet(s) found" in resp.data
    assert b"float32 capture" in resp.data


def test_upload_encrypted_packet_shows_dropped(client):
    body = build_body(PacketType.ENCRYPTED_MESSAGE, b"ciphertext-ish-bytes")
    audio = synthesize_packet(body)
    audio_int16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    write_wav(buf, 44100, audio_int16)
    buf.seek(0)

    resp = client.post(
        "/", data={"wav": (buf, "enc.wav")}, content_type="multipart/form-data"
    )

    assert b"dropped: encrypted" in resp.data
    assert b"(encrypted)" in resp.data


def test_upload_ack_packet_shows_dropped(client):
    body = build_body(PacketType.ACK, b"")
    audio = synthesize_packet(body)
    audio_int16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    write_wav(buf, 44100, audio_int16)
    buf.seek(0)

    resp = client.post(
        "/", data={"wav": (buf, "ack.wav")}, content_type="multipart/form-data"
    )

    assert b"dropped: ACK packet" in resp.data


def test_decode_upload_function_directly():
    """decode_upload() is the reusable piece; hit it without going through
    Flask's request/file-upload machinery for a faster, more direct check."""
    from werkzeug.datastructures import FileStorage

    wav = _wav_bytes("direct test message")
    fs = FileStorage(stream=io.BytesIO(wav), filename="x.wav")

    rows = web.decode_upload(fs, aliases={})

    assert len(rows) == 1
    assert rows[0]["text"] == "direct test message"
    assert rows[0]["route"] == "-> ^all"
    assert rows[0]["css"] == "ok"
