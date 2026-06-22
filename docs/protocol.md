# LPK25 mk1 SysEx protocol — working notes

> **Status: PROVISIONAL.** The LPK25 mk1 protocol is not publicly documented and
> we could not capture the official editor. Everything below is *derived* from
> the closely-related Akai **LPD8 mk1** (fully reverse-engineered) and the
> **LPK25 MK2**, and must be confirmed against real hardware. Confirmed facts
> will be marked ✅; hypotheses are marked 🟡.

## Frame structure (🟡, derived from LPD8 mk1)

```
F0 47 7F <model> <op> <len_hi> <len_lo> [data...] F7
```

| Byte(s) | Meaning |
|---------|---------|
| `F0` / `F7` | SysEx start / end |
| `47` | Akai manufacturer id ✅ |
| `7F` | broadcast device id ✅ (device answers a `F0 47 7F 76 …` frame) |
| `<model>` | product model byte — **`0x76` for LPK25 mk1** ✅ |
| `<op>` | opcode |
| `<len_hi> <len_lo>` | payload length, 16-bit big-endian as two 7-bit bytes: `(hi<<7)|lo` 🟡 |
| `data` | opcode-specific payload (7-bit bytes) |

> **Framing confirmed ✅ (2026-06-22, real LPK25 mk1).** `lpk25 identify` got a
> get-active-program reply that parses back as a frame with model `0x76`, so the
> manufacturer (`47`), broadcast device id (`7F`), model (`76`) and opcode `0x64`
> all round-trip on hardware. Length encoding still to be cross-checked against a
> real program dump.

### Confirmed device facts

- Manufacturer: **Akai Professional**; Model: **LPK25**; Version **1.0**; 2009-05-15. ✅
- Manufacturer / non-commercial **System Exclusive: Yes** (transmit + recognize). ✅
- **Device Inquiry: YES** ✅ — *contradicts the MIDI Implementation Chart, which
  lists it as No.* Real hardware answers `F0 7E 7F 06 01 F7` with:
  - manufacturer `0x47` (Akai), family LSB **`0x76`** / MSB `0x00`, member **`25`**
    (`0x19`, = the key count).
  - a non-standard **24-byte** version tail (`00 00 66 00 …`), not the usual 4
    bytes; recorded raw, meaning TBD.
  - **The family LSB equals the model byte**, giving a second, independent
    confirmation of `0x76`.
- MIDI Clock: *recognized* (external sync) but not transmitted; Program Change /
  Bank Select / Pitch Bend / Aftertouch / NRPN / RPN: none.
- Number of presets: **4**; MIDI channels 1–16. ✅

### Model byte

- LPD8 mk1 = `0x75` ✅ (from `lpd8editor`).
- LPK25 mk1 = **`0x76`** ✅ — confirmed twice on real hardware: the Device
  Inquiry reply's family LSB is `0x76`, **and** of the probed candidates
  (`0x76 0x77 0x74 0x73 0x78 0x79 0x72 0x7A 0x75`) only `0x76` answered a
  get-active-program request (`probe_models`); all others were silent.

## Opcodes (🟡, consistent across the family)

| Opcode | Direction | Meaning | Request data | Reply |
|--------|-----------|---------|--------------|-------|
| `0x63` | host→dev | get program | `[slot]` (1–4) | same opcode + payload |
| `0x61` | host→dev | send program | `[slot, payload...]` | none |
| `0x62` | host→dev | activate program | `[slot]` | none |
| `0x64` | host→dev | get active program | `[]` | same opcode + `[slot]` |

## Program payload (🟡 — biggest unknown)

The LPK25 has no pads/knobs (unlike the LPD8), so its payload is small and
LPK25-specific. The official editor exposes these parameters:

| Parameter | Range |
|-----------|-------|
| MIDI channel | 1–16 |
| Keybed octave | −4 … +4 |
| Transpose | −12 … +12 |
| Arp on/off | bool |
| Latch | bool |
| Arp mode | Up, Down, Exclusive, Inclusive, Order, Random |
| Clock | Internal / External |
| Tempo | 30–240 BPM (**> 7 bits → probably 2 bytes**) |
| Tempo taps | 2 / 3 / 4 |
| Time division | 1/4 … 1/32T (8 values) |
| Arp octave | 1 / 2 / 3 / 4 |

### Byte map (`src/lpk25/codec.py`)

`data[0]` is the slot echo. **Payload length = 13 bytes (idx 0–12), confirmed**
from the first real dump (2026-06-22). Sample dump — program 1, octave +1, arp
off:

```
01 00 05 0c 00 03 05 00 00 03 00 1e 00
 0  1  2  3  4  5  6  7  8  9 10 11 12
```

| idx | field | status |
|-----|-------|--------|
| 0 | slot echo | ✅ 1–4 |
| 1 | midi_channel? | 🟡 `byte+1`→ch 1; editor-only, can't panel-test |
| 2 | **keybed_octave** | ✅ **CONFIRMED** — value = `byte−4` (`00`=−4, `04`=0, `08`=+4; clamps, no wrap) |
| 3 | transpose? | 🟡 `0c`=12 → 0 with `byte−12`; editor-only, can't panel-test |
| 4 | **arp_enabled** | ✅ **CONFIRMED** — Arp On/Off flips only this byte (`00`↔`01`) |
| 5 | **arp_mode** | ✅ **CONFIRMED** — Up=`0`, Exclusive=`3` observed. Codes follow the *editor* order (Up,Down,Inclusive,Exclusive,Order,Random), **not** the keybed label order (which prints excl before incl) |
| 6 | **time_division** | ✅ **CONFIRMED** — hold-ARP + `1/8` key → `2`; standard order 1/4…1/32T = 0…7 |
| 7 | arp_latch? | 🟡 editor-only (no keybed control) — `00` |
| 8 | clock? | 🟡 editor-only (no keybed control) — `00` |
| 9 | tempo_taps? | 🟡 editor-only — `03` (= default 3 taps) |
| 10–11 | **tempo** | ✅ **CONFIRMED** — 14-bit `(idx10<<7)\|idx11`, range 30–240 (fast tap → idx10 `00`→`01`, value 226) |
| 12 | **arp_octave** | ✅ **CONFIRMED** — hold-ARP + `arp oct 3` key → `3`; direct 0–3 |

> **Mapping status (2026-06-23):** every **panel-settable** parameter is now
> confirmed by change-one-setting-and-diff on real hardware: `octave` (idx 2),
> `arp_enabled` (idx 4), `arp_mode` (idx 5), `time_division` (idx 6),
> `tempo` (idx 10–11), `arp_octave` (idx 12). The remaining bytes are all
> **editor-only** (the mk1 keybed has no control for them): `midi_channel`
> (idx 1), `transpose` (idx 3), and `arp_latch`/`clock`/`tempo_taps` (idx 7/8/9).
> These will be confirmed via the write path + behavioural oracle (e.g. write a
> channel, play a key, read the note-on channel back off `monitor`). Raw bytes
> are always exact regardless.
>
> Hardware controls observed on the user's unit: keys labeled (after the time-
> division keys) `up down excl incl order rand`, `arp oct 0..3`, `prog 1..4`;
> plus 6 buttons: ARP ON/OFF, TAP TEMPO, SUSTAIN, PROGRAM, OCTAVE −/+.

### Read reliability (fixed 2026-06-22)

The first `get` after powering on / touching the keyboard could fail with
`frame too short (3 bytes)` — a stray Channel message (sustain CC, active
sensing) was being read instead of the SysEx reply. `MidoTransport.request`
now skips non-`F0…F7` traffic until the real reply arrives or it times out.

## How we confirm each item (no official editor available)

1. **Identify** — `lpk25 identify`. Device Inquiry *does* answer (family LSB =
   model byte `0x76`) and the model probe agrees; confirms model + framing.
2. **Round-trip integrity** — read a program, send the same bytes back, read
   again; identical ⇒ framing + read + write are correct, independent of field
   meanings.
3. **Hardware-assisted mapping** (no editor needed) — on the device, hold
   **ARP ON/OFF** and press a labeled key to set **Time Division**, **Arp Mode**,
   or **Arp Octave**; then `dump` and see which byte changed. Directly maps
   those three fields.
4. **Behavioural oracle** — write one changed field, then play the keyboard and
   watch `lpk25 monitor`. The keyboard's own MIDI output reveals the meaning:
   MIDI channel (note-on channel), octave/transpose (note numbers), arp mode
   (note order), tempo (timing), etc.
4. Record confirmed facts here, flip the relevant `Field.verified` flags in
   `codec.py`, and adjust offsets/encodings as data, not code.

## Sources

- LPD8 mk1 protocol: `charlesfleche/lpd8editor` `doc/SYSEX.md`.
- LPK25 MK2 protocol: `denizegememetoglu/lpk25-linux` `docs/protocol.md`.
- LPK25 mk1 parameter list: official *LPK25 Editor User Guide* (Akai).

### Evaluated, no protocol info (don't re-check)

`ahuertam/akai25`, `bencevans/lpk25-console`, `bencevans/lpk25.js` are all
note-input / Web-MIDI *playing* apps — none read or write the editor SysEx
protocol (`akai25` even opens MIDI with `{ sysex: false }`). They only consume
the keyboard's Note On/Off output, which is the behavioural-oracle side we
already handle. See `docs/discovery-checklist.md` for the field-mapping plan.
