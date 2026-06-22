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
| `7F` | broadcast device id 🟡 |
| `<model>` | product model byte — **unknown for LPK25 mk1** 🟡 |
| `<op>` | opcode |
| `<len_hi> <len_lo>` | payload length, 16-bit big-endian as two 7-bit bytes: `(hi<<7)|lo` 🟡 |
| `data` | opcode-specific payload (7-bit bytes) |

### Confirmed device facts (official MIDI Implementation Chart)

- Manufacturer: **Akai Professional**; Model: **LPK25**; Version **1.0**; 2009-05-15. ✅
- Manufacturer / non-commercial **System Exclusive: Yes** (transmit + recognize). ✅
- **Device Inquiry: No** ❌ — the device does *not* answer `F0 7E 7F 06 01 F7`,
  so the model byte must be found by **probing**, not inquiry.
- MIDI Clock: *recognized* (external sync) but not transmitted; Program Change /
  Bank Select / Pitch Bend / Aftertouch / NRPN / RPN: none.
- Number of presets: **4**; MIDI channels 1–16. ✅

### Model byte

- LPD8 mk1 = `0x75` ✅ (from `lpd8editor`).
- LPK25 mk1 = **unknown**. Provisional guess `0x76`; candidates probed:
  `0x76 0x77 0x74 0x73 0x78 0x79 0x72 0x7A 0x75`. Found via `probe_models`
  (send get-active/get-program per candidate, watch for a matching reply).

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

### Provisional byte map (`src/lpk25/codec.py`)

`data[0]` is the slot echo. Indices below are into the data payload. **All
unverified** — ordering borrowed from the MK2 (minus swing):

| idx | field | encoding |
|-----|-------|----------|
| 0 | slot echo | 1–4 |
| 1 | midi_channel | byte+1 → 1–16 |
| 2 | keybed_octave | TBD (offset vs two's-complement) |
| 3 | transpose | TBD |
| 4 | arp_enabled | 0/1 |
| 5 | arp_latch | 0/1 |
| 6 | arp_mode | enum 0–5 |
| 7 | time_division | enum 0–7 |
| 8 | clock | 0/1 |
| 9 | tempo_taps | 2–4 |
| 10 | tempo | TBD (likely 2 bytes; 30–240 > 7 bits) |
| 11 | arp_octave | 0–3 (confirmed range) |

The true payload length comes from the first real dump's `<len>` field.

## How we confirm each item (no official editor available)

1. **Identify** — `lpk25 identify`. Device Inquiry won't answer (see above), so
   this is really the **model probe**: confirms the model byte and that the
   framing is right (we get *a* reply).
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
