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

### Layers

- **nunu_decoder.py** — PCM 44100 Hz capture, bandpass filter, FSK demodulation (Goertzel / zero-crossing), syncword detection (`0x30 0x72 0x57 0x6C`)
- **nunu_parser.py** — CRC-8 validation, header type extraction, plaintext payload extraction
- **mesh_bridge.py** — Routing logic (`@alias` / `@nodeid` → direct message, no prefix → broadcast), Meshtastic injection via `meshtastic` Python API
- **capture.py** — Audio capture utility from USB soundcard

### NUNU Packet (56 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | Sync | `0x30 0x72 0x57 0x6C` |
| 4 | 1 | Header | Type (bits 7-3), hop count (bits 2-0, max 7) |
| 5 | 30 | Payload | Plaintext or ChaCha20 ciphertext |
| 35 | 13 | Nonce | Encryption nonce |
| 48 | 8 | CRC | Integrity check (discard on mismatch) |

Header types: `Plain text`, `Encrypted (ChaCha20)`, `Invalid`.

## Status

**Phase 1 — Python decoder on PC** (in progress)

- [x] Audio capture from USB soundcard (Kenwood → 2.5mm → PC)
- [ ] FSK demodulation + syncword detection
- [ ] CRC validation + payload extraction
- [ ] Meshtastic bridge integration

**Phase 2 — C++ native port to Cardputer** (ESP32-S3 + SPI LoRa)

**Phase 3 — Integrated hardware** (disassembled UV-K5 + Pi Zero 2W + Heltec LoRa V3, ABS enclosure)

## Dependencies

```bash
pip install sounddevice scipy numpy meshtastic pyserial flask
```

## Hardware Targets

| Phase | Platform | Role |
|-------|----------|------|
| 1 | Mac + USB soundcard | Prototype / decoder dev |
| 2 | Cardputer (ESP32-S3) | Standalone embedded gateway |
| 3 | UV-K5 + Pi Zero + Heltec LoRa | Integrated field unit |

## Regulatory

- Callsign EA3JHL, Spanish amateur radio bands
- Plaintext only (no ChaCha20) — RRAE compliant
- LoRa 868 MHz ISM band (license-free, duty cycle < 1 %)

## References

- [uv-k5-firmware-custom (kamilsss655) — NUNU firmware](https://github.com/kamilsss655/uv-k5-firmware-custom)
- [ESPRI — Kenwood interface hardware](https://github.com/kamilsss655/ESPRI)
- [Meshtastic Python API](https://python.meshtastic.org)
- BK4819 datasheet (public PDF)

## License

Open source. Operation under EA3JHL.
