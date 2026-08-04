# ORCA — Open RF Converter & Adapter

Bidirectional gateway between the NUNU digital messaging protocol (FSK over FM on Quansheng UV-K5) and the Meshtastic LoRa mesh network.

## The Problem

Two digital mesh ecosystems that do not interoperate:

| Protocol | PHY | Frequency | Maturity |
|----------|-----|-----------|----------|
| **NUNU** | FSK over FM (BK4819) | VHF/UHF | Emerging, ham radio |
| **Meshtastic** | LoRa | 868 MHz ISM | Mature, urban EU coverage |

ORCA translates packets between both without modifying either endpoint.

## System Architecture

```
UV-K5 (NUNU FW) ──► Kenwood 2.5mm audio ──► ADC/USB ──► nunu_decoder.py
                                                              │
                                                              ▼
                                                        nunu_parser.py
                                                              │
                                                              ▼
                                                        mesh_bridge.py
                                                              │
                                                              ▼
                                                   Heltec LoRa 32 V3 ◄──► Meshtastic mesh
```

`main.py` wires the four modules above into one runnable pipeline
(`--input file.wav` for offline decoding, `--device` for live capture,
`--dry-run` to try it without a Meshtastic radio attached). See
[docs/architecture.md](docs/architecture.md) for the full picture.

### Layers

- **nunu_decoder.py** — PCM 44100 Hz capture, bandpass filter, FSK demodulation (Goertzel), clock recovery (phase search + bit-level sync search), confidence-based dedup
- **nunu_parser.py** — header type extraction, plaintext payload extraction (no CRC — see below)
- **mesh_bridge.py** — Routing logic (`@alias` / `@nodeid` → direct message, no prefix → broadcast), Meshtastic injection via `meshtastic` Python API
- **manage_aliases.py** — CLI for `alias_store.json` (add/remove/list) instead of hand-editing JSON
- **capture.py** — Audio capture utility from USB soundcard
- **main.py** — orchestrates the above; see `python main.py --help`

Full protocol reference: [docs/nunu_protocol.md](docs/nunu_protocol.md).
Wiring notes: [docs/wiring.md](docs/wiring.md).

### NUNU Packet — verified against firmware source

44 bytes after the sync word (1 header + 30 payload + 13 nonce) — **not**
56, and there is **no CRC**: the BK4819's hardware CRC is explicitly
disabled for messenger packets, and the firmware's software CRC driver
is never called for them. Both were wrong in earlier drafts of this
doc. Full corrected packet layout, header enum, FSK tone/baud details,
the encryption scheme, and the open question about mesh hopping are all
in **[docs/nunu_protocol.md](docs/nunu_protocol.md)** — that file is now
the source of truth for the protocol, kept here only as a summary so it
doesn't drift out of sync.

## Status

**Phase 1 — Python decoder on PC** (in progress)

- [x] Audio capture from USB soundcard (Kenwood → 2.5mm → PC)
- [x] Packet spec verified against firmware source (corrected: 44-byte body, no CRC, plain enum header)
- [x] Header parsing + payload extraction (`nunu_parser.py`)
- [x] Mesh routing logic (`mesh_bridge.py`) + alias management CLI
- [x] FSK demodulation + clock recovery (`nunu_decoder.py`) — **validated only against its own synthetic signal (`tests/synth_nunu.py`), not real UV-K5 audio**
- [x] Pipeline orchestration (`main.py`, offline + live modes) — offline path exercised end-to-end, live path unexercised (no audio device in dev/CI)
- [x] Test suite (38 tests) + CI running it on every push
- [ ] End-to-end validation with real hardware — **the actual blocker**; `tests/samples/` has zero real captures. See [docs/architecture.md](docs/architecture.md) "Test strategy."

**Phase 2 — C++ native port to Cardputer** (ESP32-S3 + SPI LoRa) — not started; see docs/architecture.md for why this is waiting on Phase 1 hardware validation first

**Phase 3 — Integrated hardware** (disassembled UV-K5 + Pi Zero 2W + Heltec LoRa V3, ABS enclosure) — not started

## Dependencies

```bash
pip install -r requirements.txt
```

(`sounddevice`, `scipy`, `numpy`, `matplotlib` for capture/DSP; `meshtastic`,
`pyserial` for the mesh side; `flask` reserved for a future web UI;
`pytest` for the test suite.)

## Development

```bash
python -m pytest tests/ -v                                   # run the test suite
python main.py --input tests/samples/some_capture.wav --dry-run -v   # try the pipeline
python main.py --list-devices                                # find your soundcard's device index
python bridge/manage_aliases.py list                          # inspect the alias table
```

## Hardware Targets

| Phase | Platform | Role |
|-------|----------|------|
| 1 | Mac + USB soundcard | Prototype / decoder dev |
| 2 | Cardputer (ESP32-S3) | Standalone embedded gateway |
| 3 | UV-K5 + Pi Zero + Heltec LoRa | Integrated field unit |

## Regulatory

- Callsign required, Spanish amateur radio bands
- Plaintext only (no ChaCha20) — RRAE compliant
- LoRa 868 MHz ISM band (license-free, duty cycle < 1 %)

## Documentation

- [docs/nunu_protocol.md](docs/nunu_protocol.md) — full protocol spec, verified against firmware source
- [docs/architecture.md](docs/architecture.md) — module responsibilities, data flow, test strategy, known limitations
- [docs/wiring.md](docs/wiring.md) — Kenwood-jack audio interface notes
- [AGENTS.md](AGENTS.md) — project context for AI coding agents working in this repo

## References

- [uv-k5-firmware-custom (kamilsss655) — NUNU firmware](https://github.com/kamilsss655/uv-k5-firmware-custom)
- [ESPRI — Kenwood interface hardware](https://github.com/kamilsss655/ESPRI)
- [Meshtastic Python API](https://python.meshtastic.org)
- BK4819 datasheet (public PDF)

## License

Open source. Operation under registered amateur radio callsign.
