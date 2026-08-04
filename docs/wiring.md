# Audio interface wiring notes

Phase 1 needs one thing electrically: the UV-K5's Kenwood-jack speaker
output tapped into a USB soundcard's line/mic input, at a level and
coupling the soundcard can actually digitize. **Nobody has built or
tested this cable for ORCA yet** — everything below is reference
material for doing that, not a confirmed ORCA build.

## Where the pinout comes from

The UV-K5's Kenwood-style connector pinout is **not re-derived here** —
the NUNU firmware's own README points to
[ludwich66/Quansheng_UV-K5_Wiki: Programming-Cable](https://github.com/ludwich66/Quansheng_UV-K5_Wiki/wiki/Programming-Cable)
as the reference, and that's the source to check for which ring/sleeve
of the physical jack carries which signal. Don't guess this from
speaker-cable-color folklore; the wiki page is the authoritative source
the firmware author himself points to.

## Reference implementation: ESPRI's analog front-end

[kamilsss655/ESPRI](https://github.com/kamilsss655/ESPRI) is a related
(not ORCA) project: an ESP32 "hat" that clips onto the same Kenwood
connector to give the UV-K5 WiFi, an SD card, and a web UI. It is
**not** what ORCA Phase 1 needs — no ESP32, no WiFi, no SD card — but
its schematic (`hardware/v2/schematic.pdf` in that repo) already solved
"how do you electrically tap this radio's audio in and out," which is
exactly ORCA's Phase 1 problem, just feeding an ESP32 ADC/DAC instead of
a USB soundcard's line in/out. Worth reading as a working example before
designing a Mac-facing cable from scratch. Relevant part of that
schematic (radio-side signal names as ESPRI labels them; PTT, SD card,
and battery-monitoring circuitry omitted here as not relevant to ORCA):

**Radio speaker output → ADC input** (this is the direction ORCA's
`decoder/capture.py` cares about):

```
RADIO SPK+ ──C7 (100nF)──┬── AUDIO IN PIN
                          │
                    R7 (100k) to +3.3V, C8 (4.7nF) in parallel
                    R14 (100k) to +3.3V, C9 (4.7nF) in parallel
```

C7 AC-couples the radio's speaker output (which swings around its own
bias point, not USB-audio line level) before the resistor network
re-biases it into the ADC's usable input range. A USB soundcard's
line/mic input is a different load than an ESP32 ADC pin, so these
exact values (100k/4.7nF) shouldn't be copied blindly — but the
principle (AC-couple, don't feed the radio's raw speaker line straight
into a line-in expecting to just work) is the thing to keep.

**DAC output → radio mic input** (only relevant to ORCA if it ever
transmits, which is out of scope for Phase 1 — decode-only for now):

```
AUDIO OUT PIN ──R1 (330Ω)──┬──C11 (100nF)──R10 (3.3k)──C1 (4.7µF 25V)── RADIO MIC+
                            │
                       C2 (100nF) to GND
```

## What Phase 1 actually needs

The realistic starting point is much simpler than replicating ESPRI's
board: a cable from the UV-K5's Kenwood jack (speaker-out ring, per the
pinout wiki above, plus ground) into a USB soundcard's mic/line-in,
probably through a simple coupling capacitor and maybe a resistive
attenuator if the speaker output is too hot for the soundcard's input
— consumer soundcards are generally more tolerant of arbitrary AC input
levels than a bare microcontroller ADC pin is, so this may need nothing
more than a capacitor and the right connector. Verify actual levels with
`decoder/capture.py`'s live waveform display (clipping vs. too-quiet)
before assuming a component value from either this doc or ESPRI's
schematic is right for a specific soundcard.

## Open items

- No confirmed working cable/adapter for ORCA exists yet.
- Exact Kenwood jack ring assignment: see the pinout wiki, not
  re-stated here to avoid a second, potentially-drifting copy of it.
- Whether a bare capacitor is sufficient or a resistive divider is also
  needed depends on the specific soundcard's input sensitivity — no
  data yet.
