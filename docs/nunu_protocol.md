# NUNU protocol reference

Verified 2026-08-04 against the actual firmware source —
[kamilsss655/uv-k5-firmware-custom](https://github.com/kamilsss655/uv-k5-firmware-custom),
specifically `app/messenger.c`, `app/messenger.h`, `driver/crc.c`,
`driver/bk4819.c`, and `helper/crypto.c` — not the project wiki or any
paraphrase of it. Earlier drafts of ORCA's own docs (README.md,
AGENTS.md) got three things about this protocol wrong before this
verification pass; this document is the corrected, detailed version they
now summarize. Where something below is inferred rather than read
directly from source, it says so explicitly — treat those as working
assumptions, not fact, until checked against a real capture (see
`tests/samples/`, currently empty).

## Physical layer

NUNU is 2-tone FSK, audio-coupled through a normal FM voice channel (not
direct RF FSK) — the BK4819 baseband chip either does "direct FM" keying
(deviates the RF carrier directly, no audible tones) or true audible
dual-tone AFSK, depending on modulation mode:

| `ModemModulation` enum | BK4819 REG_58 TX/RX mode | Character | Tone2 (REG_72) |
|---|---|---|---|
| `MOD_FSK_450` | mode 0: "no tones, direct FM" | for bad conditions | 450 Hz |
| `MOD_FSK_700` | mode 0: "no tones, direct FM" | for medium conditions | 700 Hz |
| `MOD_AFSK_1200` | mode 1 TX / mode 7 RX: "FFSK 1200/1800" | for good conditions | 1200 Hz |

Only `MOD_AFSK_1200` is real audible dual-tone AFSK; the other two
frequency-modulate the carrier directly inside the chip, with no fixed
audio tone pair a soundcard capture could Goertzel/zero-cross against.
**ORCA's decoder (`decoder/nunu_decoder.py`) only targets
`MOD_AFSK_1200`** — if the far end is configured for `MOD_FSK_450` or
`MOD_FSK_700`, this decoder architecture doesn't apply and would need a
different approach entirely (baseband/discriminator-level bit slicing,
not audio-tone detection).

Tone frequencies above are exact, derived from the firmware's own
`scale_freq()` (`driver/bk4819.c`): `reg = round(freq_hz * 1353245 /
131072)`. Cross-checked against a second source in the same file
(`BK4819_REG_72, 0x3065 // Set Tone-2 to 1200Hz`, and 0x3065 = 12389 =
the exact `TONE2_FREQ` firmware uses for `MOD_AFSK_1200`) — both give
1200 Hz, so this conversion is solid.

**Baud rate is not confirmed from source.** The firmware only sets chip
registers; it never states bits/second anywhere in code or comments.
ORCA's decoder assumes **1200 baud**, inferred from the "FFSK 1200/1800"
name and indirectly supported by the tone choice: at 1200 baud and
44.1 kHz, the mark tone (1200 Hz) completes exactly 1 cycle per bit and
the space tone (1800 Hz) exactly 1.5 — a clean small-integer relationship
that's the classic reason real FFSK schemes pick their tones relative to
their baud rate. Suggestive, not proof.

## Sync word

4 bytes, hardware-matched by the BK4819 itself (not software):

```
BK4819_REG_5A = 0x3072   // sync byte 0 = 0x30, sync byte 1 = 0x72
BK4819_REG_5B = 0x576C   // sync byte 2 = 0x57, sync byte 3 = 0x6C
```

→ **`0x30 0x72 0x57 0x6C`**, confirmed correct in ORCA's original docs.
Because it's matched in hardware, it is consumed before data reaches the
RX FIFO — real firmware software never sees these 4 bytes as part of
`dataPacket`. ORCA's software decoder, working from raw audio instead of
the chip's FIFO, has to find this pattern itself; see
`decoder/nunu_decoder.py`'s bit-level sync search.

Preamble: `BK4819_REG_58` bit 4 ("FSK preamble type selection") is set to
0, described in firmware comments as "0xAA or 0x55 due to the MSB of FSK
sync byte 0" — i.e. an alternating-bit training sequence precedes the
sync word, standard for FSK symbol-timing lock. Exact preamble length is
not specified in source.

## Packet body — 44 bytes, not 56

```c
// app/messenger.h
enum { NONCE_LENGTH = 13, PAYLOAD_LENGTH = 30 };

union DataPacket {
  struct {
    uint8_t       header;
    uint8_t       payload[PAYLOAD_LENGTH];   // 30
    unsigned char nonce[NONCE_LENGTH];       // 13
  } data;
  uint8_t serializedArray[1 + PAYLOAD_LENGTH + NONCE_LENGTH];  // 44
};
```

This is exactly what `BK4819_REG_5D` (packet-size register) is
programmed with — `sizeof(dataPacket.serializedArray)`, i.e. 44, rounded
up for RX framing. There is no separate length field; both ends are
hardcoded to this fixed size.

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | Header | see below — plain enum, not bit-packed |
| 1 | 30 | Payload | plaintext, or ChaCha20 ciphertext if encrypted |
| 31 | 13 | Nonce | always present, even in plaintext packets (unused then) |

Total after the sync word: **44 bytes**. ORCA's original docs claimed 56
(sync 4 + header 1 + payload 30 + nonce 13 + CRC 8) — the extra 8 bytes
never existed; see next section.

### Header (`PacketType` enum, `app/messenger.h`)

Not bit-packed — earlier ORCA drafts described "type in bits 7-3, hop
count in bits 2-0 (max 7)"; the real header is a single flat `uint8_t`
holding one of:

| Value | Name |
|---|---|
| 100 | `MESSAGE_PACKET` |
| 101 | `ENCRYPTED_MESSAGE_PACKET` |
| 102 | `ACK_PACKET` |
| 103 | `INVALID_PACKET` |

No hop-count bits exist anywhere in this header. See "Mesh hopping"
below.

## There is no CRC

This is the biggest correction from ORCA's original spec. Two
independent pieces of evidence, both from `app/messenger.c`:

1. **BK4819 hardware CRC is explicitly disabled** for messenger packets:
   ```c
   // disable CRC
   BK4819_WriteRegister(BK4819_REG_5C, 0x5625);
   ```
2. The firmware does have a *separate* software CRC engine
   (`driver/crc.c`, `CRC_Calculate()`, CRC-16-CCITT, 16-bit output) — but
   grepping all of `messenger.c` for `CRC_Calculate` or any use of that
   driver turns up nothing. It's used elsewhere in the firmware (e.g.
   flash/EEPROM integrity), never for over-the-air messenger packets.

So there is **no integrity check of any kind** on a NUNU packet, whether
plaintext or encrypted (see below — the encryption isn't authenticated
either). A receiver has exactly two framing signals to trust a packet:
the sync word matched, and the body decoded to a valid 44 bytes with a
known header enum value. Neither says anything about whether the 30
payload bytes are correct. `decoder/nunu_parser.py` reflects this
directly: `parse_body()` has no checksum step because there is nothing
to check.

## Encryption

`ENABLE_ENCRYPTION` wraps outgoing payloads in ChaCha20 (`external/chacha`,
wrapped by `helper/crypto.c`):

```c
void CRYPTO_Crypt(void *input, int input_len, void *output,
                   void *nonce, const void *key, int key_len);
```

- Plain **ChaCha20 stream cipher only — no Poly1305, no AEAD, no
  authentication tag.** Confidentiality without integrity: an attacker
  (or plain radio noise) can flip ciphertext bits and the receiver has
  no way to detect it, same as the plaintext case.
- 256-bit key (`gEncryptionKey[32]`), derived from a value stored in the
  radio's EEPROM via a salted hash (`encryptionSalt`, 4x8-byte salts,
  one per 8-byte key chunk) — "we never actually use the key stored in
  eeprom directly" per the firmware's own comment. This implies a
  shared-secret model (both radios pre-configured with the same key via
  their menu), not any kind of key exchange.
- The 13-byte nonce field in every packet is exactly `NONCE_LENGTH`
  from `CRYPTO_Crypt`'s nonce parameter.

ORCA does not implement decryption. This isn't just RRAE compliance for
transmission — there's no key-management scheme documented anywhere
(how a key would be provisioned into ORCA, rotated, or scoped per
correspondent) to implement it safely against even if the regulatory
question were moot. `nunu_parser.NunuPacket.is_encrypted` exists so ORCA
can recognize and skip encrypted traffic rather than garble it into the
mesh as if it were plaintext.

## Mesh hopping — open question

The firmware's own top-level README advertises "message hopping mesh
network functionality which allows to extend the range... via
intermediate stations." No hop-count field, TTL, or relay/rebroadcast
logic was found anywhere in `app/messenger.c` on the branch checked here
(`git log -1 -- app/messenger.c` → `5be5b19`, a docs-only merge commit).
Possibilities, unresolved:

- Flood rebroadcast with no hop limit (every node that hears a packet
  repeats it) — would explain the "no hop count needed" header design,
  at the cost of no loop prevention that's visible in this file.
  Actually got same-message dedup would need to happen somewhere.
  This is speculation, not "the answer."
- Implemented in a part of the tree not searched here.
- A feature described ahead of (or after) the code that implements it.

Doesn't block ORCA: `mesh_bridge.py`'s own `@alias`/`@nodeid` routing
operates on the *decoded plaintext payload*, independent of whatever the
NUNU header does or doesn't carry.

## Regulatory (RRAE, Spain)

Callsign EA3JHL. Spanish amateur radio rules require plaintext-only
transmission — `ENABLE_ENCRYPTION` must stay off for anything ORCA
itself transmits. Since NUNU has no integrity check regardless of
encryption, this is purely a legal constraint, not a reliability
tradeoff either way.

## Summary of corrections from earlier ORCA docs

| Claim | Was | Now |
|---|---|---|
| Body size after sync | 56 bytes | **44 bytes** |
| CRC | 8-byte field, "discard on mismatch" | **does not exist** |
| Header | bits 7-3 type, bits 2-0 hop count | **flat 1-byte enum, no hop bits** |
| Sync word | `0x30 0x72 0x57 0x6C` | unchanged — confirmed correct |
| Tone frequencies | 450/700/1200 Hz | unchanged — confirmed correct |
