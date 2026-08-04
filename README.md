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
- **nunu_parser.py** — header type extraction, plaintext payload extraction (no CRC — see below)
- **mesh_bridge.py** — Routing logic (`@alias` / `@nodeid` → direct message, no prefix → broadcast), Meshtastic injection via `meshtastic` Python API
- **capture.py** — Audio capture utility from USB soundcard

### NUNU Packet — verified against firmware source

The table below was corrected against the actual firmware (`app/messenger.c`,
`driver/crc.c` in
[uv-k5-firmware-custom](https://github.com/kamilsss655/uv-k5-firmware-custom)),
not just the wiki description. The original draft here was wrong on three
points — kept as a diff so it's clear what changed and why:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | Sync | `0x30 0x72 0x57 0x6C` — hardware-matched by the BK4819 (`REG_5A`=`0x3072`, `REG_5B`=`0x576C`); **not** delivered into the RX FIFO, so a software decoder still has to find it in the raw audio itself |
| 4 | 1 | Header | Plain `uint8_t` enum, **not** bit-packed type+hopcount: `100`=MESSAGE_PACKET, `101`=ENCRYPTED_MESSAGE_PACKET, `102`=ACK_PACKET, `103`=INVALID_PACKET |
| 5 | 30 | Payload | Plaintext or ChaCha20 ciphertext |
| 35 | 13 | Nonce | Encryption nonce (struct field is always present, even on plaintext packets) |
| — | — | ~~CRC~~ | **Does not exist.** The BK4819's hardware CRC engine is explicitly disabled for messenger packets (`// disable CRC`, `REG_5C`=`0x5625`), and the firmware's separate CRC-16-CCITT driver (`driver/crc.c`) is never called from `messenger.c`. There is no integrity check on NUNU packets on the air. |

**Total on-air data is 44 bytes after the sync word (1+30+13), not 56.** A
decoder that trusts sync+56 and checks a CRC-8 that isn't there will
misalign every packet after the first.

Open question: the firmware's own README advertises "message hopping mesh
network" but no hop-count field or relay/TTL logic was found in
`app/messenger.c` — hopping may be simple flood-rebroadcast, may live
elsewhere in the tree, or may not be in this branch yet. Doesn't block
ORCA's bridge routing, since `@alias`/`@nodeid` is parsed from the decoded
plaintext payload, not from the NUNU header.

FSK tone (`BK4819_REG_72`, inverse of the firmware's `scale_freq()`),
confirmed exactly against the register constants in `messenger.c`:

| Modulation | Tone2 |
|---|---|
| `MOD_FSK_450` | 450 Hz |
| `MOD_FSK_700` | 700 Hz |
| `MOD_AFSK_1200` | 1200 Hz |

Baud rate / bit timing is not pinned down yet — needs either the BK4819
datasheet's FSK section or a real on-air capture to confirm.

## Status

**Phase 1 — Python decoder on PC** (in progress)

- [x] Audio capture from USB soundcard (Kenwood → 2.5mm → PC)
- [x] Packet spec verified against firmware source (corrected: 44-byte body, no CRC, plain enum header)
- [x] Header parsing + payload extraction (`nunu_parser.py`) — synthetic packets only, no real capture yet
- [x] Mesh routing logic (`mesh_bridge.py`) — untested against a live Meshtastic node
- [ ] FSK demodulation + syncword detection — built against synthetic signal, **not yet validated against real UV-K5 audio**
- [ ] End-to-end validation with real hardware

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

- Callsign required, Spanish amateur radio bands
- Plaintext only (no ChaCha20) — RRAE compliant
- LoRa 868 MHz ISM band (license-free, duty cycle < 1 %)

## References

- [uv-k5-firmware-custom (kamilsss655) — NUNU firmware](https://github.com/kamilsss655/uv-k5-firmware-custom)
- [ESPRI — Kenwood interface hardware](https://github.com/kamilsss655/ESPRI)
- [Meshtastic Python API](https://python.meshtastic.org)
- BK4819 datasheet (public PDF)

## License

Open source. Operation under registered amateur radio callsign.
