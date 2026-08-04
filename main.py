#!/usr/bin/env python3
"""ORCA pipeline: UV-K5 audio -> NUNU decode -> Meshtastic bridge.

Wires together decoder/nunu_decoder.py and bridge/mesh_bridge.py into one
runnable entry point, per README's system architecture diagram. Two
input modes:

  --input FILE.wav   Offline: decode a WAV file once, route what's found,
                      exit. This is the only mode that's actually been
                      exercised (against tests/synth_nunu.py output and
                      real WAV files) -- it's the recommended way to try
                      this out before trusting the live path.
  --device [N]        Live: capture continuously from a sound device,
                      decode a rolling window, route new packets as they
                      appear. Untested against a real UV-K5 (see
                      AGENTS.md) -- exercise --input first.

--dry-run prints routing decisions instead of touching a real Meshtastic
radio. Useful for testing without a Heltec/T-Beam attached, and right
now the only way to run this end-to-end at all, since Phase 1 still has
no real UV-K5 capture to validate the decoder against.

Examples:
    python main.py --input tests/samples/capture.wav --dry-run
    python main.py --device --meshtastic /dev/ttyUSB0
    python main.py --device --meshtastic tcp:192.168.1.50
"""

import argparse
import hashlib
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "decoder"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "bridge"))

from mesh_bridge import load_aliases, route_message  # noqa: E402
from nunu_decoder import SAMPLE_RATE, decode  # noqa: E402
from nunu_parser import NunuPacket  # noqa: E402

logger = logging.getLogger("orca.main")


class DryRunInterface:
    """Stand-in for a meshtastic interface: logs instead of transmitting."""

    def sendText(self, text, destinationId):
        print(f"[dry-run] -> {destinationId}: {text}")


def _packet_fingerprint(packet: NunuPacket) -> str:
    h = hashlib.sha1()
    h.update(bytes([packet.packet_type]))
    h.update(packet.payload)
    h.update(packet.nonce)
    return h.hexdigest()


def route_packet(packet: NunuPacket, interface, aliases: dict) -> None:
    if packet.is_encrypted:
        logger.info("dropping encrypted packet: no key management yet (see AGENTS.md)")
        return
    if packet.packet_type.name in ("ACK", "INVALID"):
        logger.info("received %s packet, not routed to mesh", packet.packet_type.name)
        return
    text = packet.text()
    logger.info("NUNU -> mesh: %r", text)
    route_message(text, interface, aliases)


def run_offline(wav_path: Path, interface, aliases: dict) -> int:
    from scipy.io import wavfile

    fs, audio = wavfile.read(wav_path)
    if audio.ndim > 1:
        audio = audio[:, 0]  # first channel only
    if np.issubdtype(audio.dtype, np.integer):
        audio = audio.astype(np.float32) / 32768.0
    else:
        audio = audio.astype(np.float32)

    packets = decode(audio, fs=fs)
    logger.info("decoded %d packet(s) from %s", len(packets), wav_path)
    for packet in packets:
        route_packet(packet, interface, aliases)
    return len(packets)


def _append_to_buffer(buffer: np.ndarray, new_samples: np.ndarray, max_samples: int) -> np.ndarray:
    """Append and trim to a rolling window, oldest samples dropped first."""
    return np.concatenate([buffer, new_samples])[-max_samples:]


def _drain_and_route(
    buffer: np.ndarray, seen: dict, now: float, seen_ttl: float, interface, aliases: dict
) -> int:
    """One decode+dedupe+route pass over the current rolling buffer.

    Mutates `seen` in place: expires entries older than seen_ttl, then
    records a fresh timestamp for every packet routed this pass. Split
    out from run_live() so this -- the actual interesting logic, as
    opposed to the sounddevice plumbing around it -- is testable without
    an infinite loop or a real/mocked audio device.

    Returns how many packets were routed (not just seen) this pass.
    """
    for key in [k for k, t in seen.items() if now - t > seen_ttl]:
        del seen[key]

    routed = 0
    for packet in decode(buffer):
        fingerprint = _packet_fingerprint(packet)
        if fingerprint in seen:
            continue
        seen[fingerprint] = now
        route_packet(packet, interface, aliases)
        routed += 1
    return routed


def run_live(
    device: Optional[int],
    interface,
    aliases: dict,
    window_seconds: float = 5.0,
    poll_seconds: float = 1.0,
) -> None:
    """Continuously capture and decode a rolling audio window.

    Not validated against real hardware. Packets are deduped by content
    fingerprint with a TTL a bit longer than the window, since the same
    audio (and therefore the same packet) is decoded repeatedly for as
    long as it's still inside the rolling buffer -- without that, one
    real transmission would get routed to the mesh several times over.
    See _drain_and_route for that logic in isolation.
    """
    import sounddevice as sd

    buffer = np.zeros(0, dtype=np.float32)
    max_samples = int(window_seconds * SAMPLE_RATE)
    seen: dict[str, float] = {}
    seen_ttl = window_seconds * 2

    def callback(indata, frames, time_info, status):
        nonlocal buffer
        if status:
            logger.warning("audio status: %s", status)
        buffer = _append_to_buffer(buffer, indata[:, 0], max_samples)

    logger.info(
        "listening on device %s (Ctrl+C to stop)...",
        device if device is not None else "default",
    )
    with sd.InputStream(device=device, samplerate=SAMPLE_RATE, channels=1, callback=callback):
        while True:
            time.sleep(poll_seconds)
            if len(buffer) < SAMPLE_RATE:
                continue  # not enough audio yet for even a short packet
            _drain_and_route(buffer.copy(), seen, time.time(), seen_ttl, interface, aliases)


def build_interface(dry_run: bool, connection: Optional[str]):
    if dry_run:
        return DryRunInterface()
    from meshtastic.serial_interface import SerialInterface
    from meshtastic.tcp_interface import TCPInterface

    if connection and connection.startswith("tcp:"):
        return TCPInterface(hostname=connection[len("tcp:") :])
    return SerialInterface(devPath=connection)


def list_audio_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())


def main() -> int:
    parser = argparse.ArgumentParser(description="ORCA: NUNU <-> Meshtastic bridge")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="decode a WAV file once and exit")
    source.add_argument(
        "--device",
        type=int,
        nargs="?",
        const=-1,
        help="live capture from this sound device index (omit the index for the system default)",
    )
    source.add_argument(
        "--list-devices", action="store_true", help="list audio input devices and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print routing decisions instead of sending to a real Meshtastic radio",
    )
    parser.add_argument(
        "--meshtastic", help="meshtastic connection: a serial device path, or tcp:<host>"
    )
    parser.add_argument(
        "--aliases", type=Path, help="path to alias_store.json (default: bridge/alias_store.json)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.list_devices:
        list_audio_devices()
        return 0

    if not args.dry_run and args.meshtastic is None:
        parser.error("--meshtastic is required unless --dry-run is set")

    aliases = load_aliases(args.aliases) if args.aliases else load_aliases()
    interface = build_interface(args.dry_run, args.meshtastic)

    try:
        if args.input:
            run_offline(args.input, interface, aliases)
        else:
            device = None if args.device in (None, -1) else args.device
            run_live(device, interface, aliases)
    finally:
        if not args.dry_run and hasattr(interface, "close"):
            interface.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
