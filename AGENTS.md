# ORCA — Project Context for AI Agents

## Repo
- Path: `/Users/manuelgarcia/Documents/GitHub_Projects/ORCAv0`
- Owner: EA3JHL (Manuel Garcia), radioaficionado español
- Git repo, pushed to github.com/RockSneeze081/ORCAv0, CI runs pytest on push/PR

## Project Goal
Bidirectional gateway between NUNU (FSK over FM on Quansheng UV-K5 with custom firmware) and Meshtastic (LoRa 868 MHz mesh). Messages flow in both directions transparently.

## Stack
- Python 3.x
- `sounddevice`, `scipy`, `numpy` — audio capture + signal processing
- `meshtastic` — official Meshtastic Python API (serial/TCP)
- `pyserial` — serial comms with LoRa module
- `flask` — future web UI

## Protocol: NUNU Packet — verified 2026-08-04 against firmware source

Corrected against the real firmware (`app/messenger.c`, `driver/crc.c` in
kamilsss655/uv-k5-firmware-custom), not just the wiki. Three things below
were wrong in earlier drafts of this doc — see inline notes.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0      | 4    | Sync  | `0x30 0x72 0x57 0x6C` — HW-matched by BK4819 (`REG_5A`=`0x3072`, `REG_5B`=`0x576C`), not present in the RX FIFO bytes |
| 4      | 1    | Header| Plain `uint8_t` enum — **not** bit-packed. No hop-count bits exist. |
| 5      | 30   | Payload | Plaintext or ChaCha20 encrypted |
| 35     | 13   | Nonce | Encryption nonce (always present in the struct, even for plaintext) |
| —      | —    | ~~CRC~~ | **Does not exist on the air.** BK4819 hardware CRC is explicitly disabled for messenger packets; the firmware's software CRC-16-CCITT driver exists but is never invoked from `messenger.c`. `nunu_parser.py` must not expect or require a CRC field. |

Data after sync is **44 bytes** (1+30+13), not 56 — do not allocate an
8-byte CRC field.

### Header types (PacketType enum, `app/messenger.h`)
- `100` MESSAGE_PACKET (plain text)
- `101` ENCRYPTED_MESSAGE_PACKET (ChaCha20)
- `102` ACK_PACKET
- `103` INVALID_PACKET

### FSK tone (BK4819 REG_72, confirmed via firmware's `scale_freq()`)
| Modulation | Tone2 |
|---|---|
| `MOD_FSK_450` | 450 Hz |
| `MOD_FSK_700` | 700 Hz |
| `MOD_AFSK_1200` | 1200 Hz |

Baud rate / bit timing not yet confirmed — needs BK4819 datasheet or a real
capture. Don't hardcode a guessed value into the decoder without flagging it.

### Open question: mesh hopping
Firmware's own README advertises "message hopping mesh network" but no
hop-count/TTL/relay logic was found in `app/messenger.c` on the default
branch. May be flood-rebroadcast, may live elsewhere, may be unmerged.
Does not block `mesh_bridge.py` — its `@alias`/`@nodeid` routing reads the
decoded plaintext payload, not the NUNU header.

## Audio Pipeline (implemented in decoder/nunu_decoder.py)
- Input: PCM 44100 Hz, mono, from USB soundcard (via Kenwood 2.5mm jack on UV-K5)
- Bandpass filter around the two FFSK tones (wide -- see module docstring for
  why a tight band actively corrupts bits at symbol boundaries)
- Demodulation: per-bit Goertzel correlation at the two known tone frequencies
- Clock recovery: brute-force phase search (bit-0 offset unknown in a real
  capture), since this decoder is phase-sensitive to roughly +/-3 samples
  out of a ~37-sample bit period
- Sync-word search happens in bit-space, not after byte-packing (byte
  alignment isn't knowable in advance -- see module docstring)
- Candidates from different phases are scored by per-bit confidence and
  deduped by approximate position, not by exact content match

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

## Repo Structure

```
ORCAv0/
├── main.py                 # pipeline entry point: decoder -> parser -> bridge
├── decoder/
│   ├── nunu_decoder.py     # FSK demod + clock recovery, decode() is the entry point
│   ├── nunu_parser.py      # framing/packet parsing, decoupled from how bytes arrived
│   └── capture.py          # standalone WAV recording utility (live waveform/spectrogram)
├── bridge/
│   ├── mesh_bridge.py      # NUNU text -> Meshtastic routing
│   ├── manage_aliases.py   # CLI: add/remove/list aliases
│   └── alias_store.json
├── firmware/
│   └── cardputer/          # Phase 2 (C++ port) -- not started, see docs/architecture.md
├── hardware/
│   ├── schematic/          # Phase 4 -- not started
│   └── enclosure/          # Phase 3 -- not started
├── docs/
│   ├── nunu_protocol.md    # verified NUNU spec, corrections vs. earlier drafts
│   ├── architecture.md     # module responsibilities, data flow, test strategy
│   └── wiring.md           # Kenwood-jack audio interface notes
├── tests/
│   ├── synth_nunu.py       # synthetic FFSK signal generator, mirrors decoder's PHY assumptions
│   ├── test_nunu_parser.py
│   ├── test_nunu_decoder.py
│   ├── test_mesh_bridge.py
│   ├── test_main.py
│   └── samples/             # Real NUNU traffic WAV captures -- still EMPTY, see below
├── .github/workflows/test.yml
├── requirements.txt
├── README.md
└── AGENTS.md
```

The biggest gap is not a missing file, it's missing data: `tests/samples/`
has zero real captures, so every PHY-layer assumption in
`nunu_decoder.py` (baud rate, tone/bit polarity, bit order) is validated
only against its own synthetic signal generator, not against a real
UV-K5. See docs/architecture.md "Test strategy" before assuming the
decoder works on real audio.

## Key External References
- NUNU firmware: https://github.com/kamilsss655/uv-k5-firmware-custom
- ESPRI (Kenwood interface): https://github.com/kamilsss655/ESPRI
- Meshtastic Python API docs: https://python.meshtastic.org
- BK4819 datasheet: public PDF (search "BK4819 datasheet")

## Development Notes
- Always check existing files before creating new ones (repo may be partially populated)
- `pytest` is configured and CI-enforced: run `python -m pytest tests/ -v` before
  considering any change to decoder/, bridge/, or main.py done
- WAV samples for testing should go in `tests/samples/` (still empty — see Repo Structure above)
- Future: mesh_bridge IPC could use UDP localhost when decoder is C++ on embedded
- CRITICAL: Never commit .env, credentials, or key material

## Agent Instructions
When asked to write code for ORCA:
1. Read relevant existing files first
2. Follow the naming conventions and structure above
3. Use the verified packet format: syncword `0x3072576C` (4 bytes, HW-matched,
   not in the data) + 44-byte body (1 header + 30 payload + 13 nonce). No CRC.
4. Do not add CRC validation — there is nothing to validate against; treat
   sync-word match + correct length as the only framing check available
5. Respect RRAE: no encryption in transmitted packets
