import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decoder"))

import numpy as np
from scipy.io import wavfile

from capture import SAMPLE_RATE, list_devices, save_wav


def test_save_wav_does_not_touch_real_samples_dir(tmp_path):
    """The actual point of parameterizing save_wav: writing a test WAV
    must never land in the real tests/samples/, which is reserved for
    genuine hardware captures."""
    audio = np.zeros(SAMPLE_RATE, dtype=np.float32)

    filepath = save_wav(audio, duration=1, samples_dir=tmp_path)

    assert filepath.parent == tmp_path
    assert filepath.exists()
    real_samples_dir = Path(__file__).resolve().parent / "samples"
    assert list(real_samples_dir.iterdir()) == []


def test_save_wav_filename_includes_duration(tmp_path):
    filepath = save_wav(np.zeros(100, dtype=np.float32), duration=30, samples_dir=tmp_path)
    assert "30s" in filepath.name
    assert filepath.suffix == ".wav"


def test_save_wav_round_trips_audio_content(tmp_path):
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0] * 100, dtype=np.float32)

    filepath = save_wav(audio, duration=1, samples_dir=tmp_path)

    fs, written = wavfile.read(str(filepath))
    assert fs == SAMPLE_RATE
    assert written.dtype == np.int16
    # 16-bit round-trip: exact for 0.0, within 1 LSB of scale for the rest
    restored = written.astype(np.float32) / 32767.0
    np.testing.assert_allclose(restored, audio, atol=1.0 / 32767 + 1e-6)


def test_save_wav_creates_samples_dir_if_missing(tmp_path):
    target = tmp_path / "nested" / "samples"
    assert not target.exists()

    save_wav(np.zeros(10, dtype=np.float32), duration=1, samples_dir=target)

    assert target.exists()


def test_save_wav_clips_out_of_range_audio_instead_of_wrapping(tmp_path):
    """Regression test: float32->int16 casting doesn't clip, it wraps --
    2.0*32767 overflows int16 and silently becomes -2, not 32767. This
    used to be safe only because record_audio() happens to clip before
    calling save_wav; a direct or future caller passing unclipped audio
    would have gotten silently corrupted output, not a loud error or a
    merely-distorted-but-recognizable clipped signal."""
    audio = np.array([2.0, -2.0, 1.5, 0.5], dtype=np.float32)

    filepath = save_wav(audio, duration=1, samples_dir=tmp_path)

    _, written = wavfile.read(str(filepath))
    assert written[0] == 32767  # clipped to max, not wrapped to -2
    assert written[1] == -32767  # clipped to min, not wrapped to +2
    assert written[2] == 32767  # 1.5 clipped to 1.0 -> max
    assert written[3] == int(0.5 * 32767)  # in-range value untouched


def test_list_devices_prints_without_crashing(capsys):
    fake_devices = [
        {"name": "Built-in Mic", "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 44100.0},
        {"name": "Built-in Speakers", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 44100.0},
    ]
    with patch("capture.sd.query_devices", return_value=fake_devices):
        list_devices()

    out = capsys.readouterr().out
    assert "Built-in Mic" in out
    assert "<-- INPUT" in out
    assert "Built-in Speakers" in out
