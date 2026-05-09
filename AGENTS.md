# ORCA — Project Context for AI Agents

## Repo
- Path: `/Users/manuelgarcia/Documents/GitHub_Projects/ORCAv0`
- Owner: EA3JHL (Manuel Garcia), radioaficionado español
- Not a git repo yet (user-init only)

## Project Goal
Bidirectional gateway between NUNU (FSK over FM on Quansheng UV-K5 with custom firmware) and Meshtastic (LoRa 868 MHz mesh). Messages flow in both directions transparently.

## Stack
- Python 3.x
- `sounddevice`, `scipy`, `numpy` — audio capture + signal processing
- `meshtastic` — official Meshtastic Python API (serial/TCP)
- `pyserial` — serial comms with LoRa module
- `flask` — future web UI

## Protocol: NUNU Packet (56 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0      | 4    | Sync  | `0x30 0x72 0x57 0x6C` |
| 4      | 1    | Header| bits 7-3: type, bits 2-0: hop count (max 7) |
| 5      | 30   | Payload | Plaintext or ChaCha20 encrypted |
| 35     | 13   | Nonce | Encryption nonce |
| 48     | 8    | CRC   | Integrity check, discard on mismatch |

### Header types
- Plain text
- Encrypted (ChaCha20)
- Invalid

## Audio Pipeline
- Input: PCM 44100 Hz, mono, from USB soundcard (via Kenwood 2.5mm jack on UV-K5)
- Bandpass filter around FSK tones
- Demodulation: Goertzel correlation or zero-crossing
- Syncword detection triggers packet assembly

## Routing Logic (mesh_bridge.py)
- `@alias` or `@nodeid` prefix → direct message to that Meshtastic node
- No prefix → broadcast to `0xFFFFFFFF`
- Alias table in `alias_store.json` (name → Meshtastic node ID)

## Hardware Targets

### Current (Phase 1)
- Mac + USB soundcard + UV-K5 with NUNU firmware

### Phase 2
- Cardputer (ESP32-S3 + LoRa SPI) — native C++ port

### Phase 3
- UV-K5 (disassembled) + Pi Zero 2W + Heltec LoRa 32 V3 or TTGO T-Beam
- Enclosure in ABS

### Phase 4 (Future Hardware)
- KiCad schematic for Kenwood ↔ ADC interface
- PCB design

## Regulatory
- Callsign: EA3JHL, Spanish ham bands
- Plaintext only (no ChaCha20) for RRAE compliance
- LoRa 868 MHz ISM, license-free, duty cycle <1%

## Repo Structure (to be created)

```
ORCA/
├── decoder/
│   ├── nunu_decoder.py
│   ├── nunu_parser.py
│   └── capture.py
├── bridge/
│   ├── mesh_bridge.py
│   └── alias_store.json
├── firmware/
│   └── cardputer/
├── hardware/
│   ├── schematic/
│   └── enclosure/
├── docs/
│   ├── nunu_protocol.md
│   ├── architecture.md
│   └── wiring.md
├── tests/
│   └── samples/          # Real NUNU traffic WAV captures
├── README.md
└── AGENTS.md
```

## Key External References
- NUNU firmware: https://github.com/kamilsss655/uv-k5-firmware-custom
- ESPRI (Kenwood interface): https://github.com/kamilsss655/ESPRI
- Meshtastic Python API docs: https://python.meshtastic.org
- BK4819 datasheet: public PDF (search "BK4819 datasheet")

## Development Notes
- Always check existing files before creating new ones (repo may be partially populated)
- Test with `pytest` or just run scripts directly (no test framework configured yet)
- WAV samples for testing should go in `tests/samples/`
- Future: mesh_bridge IPC could use UDP localhost when decoder is C++ on embedded
- CRITICAL: Never commit .env, credentials, or key material

## Agent Instructions
When asked to write code for ORCA:
1. Read relevant existing files first
2. Follow the naming conventions and structure above
3. Use the exact packet format (56 bytes, syncword 0x3072576C)
4. Ensure CRC validation before routing
5. Respect RRAE: no encryption in transmitted packets
