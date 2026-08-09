# ORCA architecture

Status snapshot as of 2026-08-04. For the protocol itself, see
[nunu_protocol.md](nunu_protocol.md); this document is about how ORCA's
own code is organized, not about NUNU.

## Data flow

```
                    ┌─────────────────────── Phase 1 (this repo) ───────────────────────┐
                    │                                                                    │
UV-K5 (NUNU FW) ──► Kenwood 2.5mm ──► USB soundcard ──► decoder/nunu_decoder.py::decode()
  (untested,             audio jack        (PCM 44.1kHz)         │
   no real                                                       │ list[NunuPacket]
   hardware yet)                                                 ▼
                                                        bridge/mesh_bridge.py::route_message()
                                                                   │
                                                                   │ interface.sendText(...)
                                                                   ▼
                                                        meshtastic Python API ◄──► Heltec/T-Beam ◄──► mesh
                    │                                                                    │
                    └────────────────────────────────────────────────────────────────────┘
                    main.py wires the above together; --dry-run swaps the last hop
                    for DryRunInterface (logs instead of transmitting).
```

Everything left of "USB soundcard" — the actual UV-K5, its NUNU firmware,
the audio interface hardware — is Phase 3 (see README "Hardware
Targets"). Right now ORCA only consumes whatever PCM audio a WAV file or
system audio device hands it; nothing here has been run against a real
radio.

## Module responsibilities

**`decoder/capture.py`** — records PCM audio from a USB soundcard to a
WAV file, with a live waveform/spectrogram display for manually checking
signal presence and levels while pointing an antenna or adjusting a
Kenwood-jack cable. Standalone tool, not imported by anything else in
the pipeline; its only coupling to the rest of the code is the shared
`SAMPLE_RATE = 44100` constant and the `tests/samples/` output
directory convention.

**`decoder/nunu_decoder.py`** — the FSK demodulator. `decode(audio, fs)`
takes a PCM buffer and returns `list[NunuPacket]`. Internally:
bandpass filter → per-candidate-phase Goertzel bit slicing (clock
recovery) → bit-level sync-word search → hand off each body to
`nunu_parser.parse_body()` → confidence-based dedup across phases. Every
PHY-layer number in this file (baud rate, tone-to-bit polarity, bit
order) is a documented, unvalidated assumption — see the module
docstring and [nunu_protocol.md](nunu_protocol.md). Only targets
`MOD_AFSK_1200`; see protocol doc for why the other two NUNU modulation
modes aren't decodable this way at all.

**`decoder/nunu_parser.py`** — the framing/logical layer, decoupled from
how the bytes were obtained (decoder, a WAV file, a unit test's literal
bytes, hypothetically a future C++ port's serial output — anything that
can hand it bytes). `parse_body()` validates a 44-byte body against the
`PacketType` enum (no CRC exists to check, see protocol doc).
`find_packets()`/`find_sync_positions()` do byte-level sync-word search
with optional Hamming-distance tolerance; `nunu_decoder.py` uses its own
bit-level search instead (see that module's docstring for why: byte
alignment can't be assumed for a stream recovered from raw audio).

**`bridge/mesh_bridge.py`** — routes a decoded plaintext message onto a
Meshtastic mesh: `@alias`/`@nodeid` → direct message, no prefix →
broadcast. `route_message()` takes any object with a Meshtastic-shaped
`.sendText(text, destinationId=...)`, so it's unit-testable without a
real radio (`tests/test_mesh_bridge.py` uses a small fake). Alias table
persistence (`load_aliases`/`save_aliases`) lives here too.

**`bridge/manage_aliases.py`** — thin CLI over `mesh_bridge.py`'s alias
functions (`add`/`remove`/`list`), so `alias_store.json` doesn't need
hand-editing.

**`main.py`** — the only place all of the above get wired together.
`--input file.wav` decodes once and exits; `--device [N]` runs a
continuous capture loop with a rolling buffer and fingerprint-based
dedup (the same real packet stays inside the rolling window across
several decode passes and would otherwise get routed to the mesh
multiple times). `--dry-run` substitutes `DryRunInterface` (prints
instead of transmitting) for `meshtastic.serial_interface.SerialInterface`
/ `tcp_interface.TCPInterface`.

## What's implemented vs. what's stubbed

| Piece | Status |
|---|---|
| NUNU packet parsing | Implemented, tested against synthetic packets |
| Mesh routing logic | Implemented, tested against a fake interface |
| FSK demodulation | Implemented, tested only against synthetic audio (own encoder) |
| Clock recovery | Implemented (phase search + bit-level sync search), synthetic-tested |
| Pipeline orchestration (`main.py`) | Implemented; offline path exercised end-to-end against a synthetic WAV, live path unexercised (no audio device in dev/CI) |
| Real UV-K5 capture | **Not done.** `tests/samples/` is empty. |
| ChaCha20 decryption | Not implemented, on purpose — see nunu_protocol.md "Encryption" |
| Phase 2 (Cardputer C++ port) | Not started |
| Phase 3 (integrated hardware) | Not started |
| Phase 4 (KiCad schematic) | Not started |

Phase 2/3/4 are deliberately not underway yet. Porting an unvalidated
protocol implementation to a second language, or designing hardware
around it, would compound Phase 1's open risk (four unconfirmed PHY
parameters — baud rate, tone polarity, bit order, and whether
`MOD_AFSK_1200` is even the mode in use) rather than reduce it. The
useful next step is real audio, not more code.

## Test strategy

There is no real NUNU traffic to test against yet, so the whole test
suite is synthetic: `tests/synth_nunu.py` encodes packets using the
*same* PHY assumptions `nunu_decoder.py` decodes with. This proves
internal self-consistency — the encoder and decoder agree with each
other — and catches real implementation bugs (three were found and
fixed this way: a Goertzel bin-quantization bug that made 1200 Hz and
1800 Hz indistinguishable at this baud rate, a byte-alignment bug where
sync search assumed bit 0 of the demodulated stream fell on a true
8-bit boundary of the original transmission, and a crash on any audio
buffer shorter than one frame). It does **not** prove any of the four
PHY assumptions are correct, since the synthetic signal is generated
from those same assumptions — a systematically wrong assumption would
round-trip against itself just fine and still fail against a real
UV-K5.

The synthesizer was deliberately made harder rather than left at its
first, simplest version: it originally reset each tone's phase to 0 at
every bit boundary, which is easier to generate but unrealistic (a real
oscillator's phase evolves continuously; only the instantaneous
frequency switches). That made the self-test easier than real audio in
a way that could hide a decoder bug relying on the idealization. Now
`bits_to_audio` carries phase continuously across bit boundaries, and
the full decoder test suite still passes unmodified — evidence (not
proof) that the bit-slicing logic isn't fragile to that specific
simplification, for whatever that's worth against the much bigger
unknowns above.

Closing that gap needs one real WAV capture with a known transmitted
message. `decoder/capture.py` produces the WAV; `main.py --input
<file> --dry-run` runs it through the full decode+route path without
needing a Meshtastic radio attached.

## Known limitations (consolidated)

- **Baud rate, tone/bit polarity, bit order**: inferred, not measured —
  see nunu_protocol.md.
- **No timing-error-detector loop** (Gardner/Mueller-and-Muller):
  clock recovery is brute-force phase search over one bit period,
  correct but not efficient; fine offline, not suitable for continuous
  embedded operation as-is (relevant if Phase 2 ever starts).
- **Live capture path (`main.py --device`) is unexercised** — no audio
  input device available in this development environment.
- **No encrypted-packet handling** beyond recognizing and dropping them.
- **Mesh hop/relay behavior is unknown** — see nunu_protocol.md "Mesh
  hopping".
