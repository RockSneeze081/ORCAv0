#!/usr/bin/env python3
"""Audio capture utility for NUNU FSK signal recording.

Records mono PCM at 44100 Hz from a USB soundcard connected to
a Quansheng UV-K5 with NUNU firmware (Kenwood 2.5mm jack).

Usage:
    python decoder/capture.py -d 2 -t 30
    python decoder/capture.py --list
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as write_wav

SAMPLE_RATE = 44100
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "tests" / "samples"


def list_devices():
    devices = sd.query_devices()
    print("\nAvailable audio devices:")
    print(f"{'Idx':<5} {'Name':<50} {'Channels':<10} {'SR':<10}")
    print("-" * 75)
    for i, dev in enumerate(devices):
        ch = f"{dev['max_input_channels']} in / {dev['max_output_channels']} out"
        sr = dev.get('default_samplerate', 'N/A')
        name = dev['name'][:48]
        marker = " <-- INPUT" if dev['max_input_channels'] > 0 else ""
        print(f"{i:<5} {name:<50} {ch:<10} {sr:<10}{marker}")
    print()


def record_audio(device_index, duration, gain=1.0):
    fs = SAMPLE_RATE
    samples = int(duration * fs)
    audio = np.zeros(samples, dtype=np.float32)

    fig, (ax_wave, ax_spec) = plt.subplots(2, 1, figsize=(12, 6))
    fig.suptitle("NUNU RX — Recording", fontsize=14)
    plt.subplots_adjust(hspace=0.4)
    plt.ion()

    wave_line, = ax_wave.plot([], [], 'b-', lw=0.5)
    ax_wave.set_xlim(0, fs // 4)
    ax_wave.set_ylim(-1.1, 1.1)
    ax_wave.set_xlabel("Sample")
    ax_wave.set_ylabel("Amplitude")
    ax_wave.grid(True, alpha=0.3)

    ax_spec.set_xlabel("Time (s)")
    ax_spec.set_ylabel("Frequency (Hz)")
    ax_spec.set_ylim(0, 8000)

    window = fs // 4
    spec_data = None
    extent = None

    def callback(indata, frames, _time_info, status):
        nonlocal spec_data, extent, audio
        if status:
            print(f"Status: {status}")
        chunk = indata[:, 0] * gain
        pos = int(_time_info.inputBufferAdcTime * fs)
        end = min(pos + frames, samples)
        audio[pos:end] = chunk[:end - pos]

        if pos % window < frames:
            wave_line.set_data(range(len(chunk[:window])), chunk[:window])
            ax_wave.set_xlim(0, len(chunk[:window]))
            ax_wave.relim()
            ax_wave.autoscale_view()

            ax_spec.clear()
            ax_spec.specgram(chunk[:window], Fs=fs, NFFT=512,
                             noverlap=384, cmap='viridis')
            ax_spec.set_ylim(0, 8000)
            ax_spec.set_xlabel("Time (s)")
            ax_spec.set_ylabel("Frequency (Hz)")
            fig.canvas.draw_idle()
            fig.canvas.flush_events()

    stream = sd.InputStream(
        device=device_index,
        samplerate=fs,
        channels=1,
        blocksize=1024,
        callback=callback,
    )

    print(f"Recording {duration}s on device {device_index}...")
    stream.start()
    t0 = time.time()

    try:
        while stream.active and (time.time() - t0) < duration:
            plt.pause(0.05)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    stream.stop()
    stream.close()
    plt.ioff()
    plt.close(fig)

    audio = audio[:int((time.time() - t0) * fs)]
    audio = np.clip(audio, -1.0, 1.0)

    return audio


def save_wav(audio, duration):
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"nunu_capture_{ts}_{duration}s.wav"
    filepath = SAMPLES_DIR / filename

    audio_int16 = (audio * 32767).astype(np.int16)
    write_wav(str(filepath), SAMPLE_RATE, audio_int16)
    print(f"Saved: {filepath} ({len(audio) / SAMPLE_RATE:.1f}s, {SAMPLE_RATE} Hz, mono)")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="NUNU audio capture — record FSK-over-FM from UV-K5"
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List audio input devices and exit"
    )
    parser.add_argument(
        "-d", "--device",
        type=int,
        default=None,
        help="Input device index (default: system default)"
    )
    parser.add_argument(
        "-t", "--time",
        type=int,
        default=10,
        help="Recording duration in seconds (default: 10)"
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=1.0,
        help="Amplitude gain factor (default: 1.0)"
    )
    args = parser.parse_args()

    if args.list:
        list_devices()
        return

    audio = record_audio(args.device, args.time, args.gain)
    save_wav(audio, args.time)


if __name__ == "__main__":
    main()
