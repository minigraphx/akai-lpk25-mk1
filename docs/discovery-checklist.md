# LPK25 mk1 — field-mapping capture checklist

Goal: map every byte of the 13-byte program payload by **changing one setting at
a time** and diffing the dump. Confirmed so far: `idx 0` = slot, `idx 4` = arp
on/off. Everything else is a guess until a diff proves it.

## How it works

```bash
source .venv/bin/activate
lpk25 get 1 -o base.json          # baseline
# … change exactly ONE setting on the device …
lpk25 get 1 -o step.json
lpk25 diff base.json step.json    # prints the byte index that moved
```

`lpk25 diff` shows `idx N: 0xAA -> 0xBB` plus the mapped field name (or
`unmapped`). The index that moves IS that parameter.

## Rules that keep diffs unambiguous

- **One change per dump.** Two changes = an ambiguous diff.
- **Return to the baseline setting between steps** (or re-dump a fresh `base`),
  so each diff is against a known state.
- **Pressing keys never changes the dump** — only panel edits do. Ignore notes.
- If a diff is **empty** after a real edit, the change may not have persisted:
  reselect the program (Prog button) and/or power-cycle, then re-dump.
- Always work on **program 1** (slot is fixed) unless testing slots specifically.
- Save the JSON files — they become golden test vectors.

## The sequence

Take a fresh `base.json` first. For each row: make the change, `get -o`, `diff`,
then record which idx moved and to what value.

| # | Change on the device | Capture file | Expect to learn |
|---|----------------------|--------------|-----------------|
| 0 | nothing (reference) | `base.json` | baseline bytes |
| 1 | **Octave +1** (OCT UP ×1) | `oct_p1.json` | octave byte + encoding |
| 2 | **Octave +2** (OCT UP ×2 from base) | `oct_p2.json` | confirm step size / linearity |
| 3 | **Octave −1** (OCT DOWN ×1 from base) | `oct_m1.json` | sign encoding (offset vs two's-complement) |
| 4 | **Transpose +1** (hold TRANSPOSE + key up) | `tr_p1.json` | transpose byte |
| 5 | **Transpose −1** (hold TRANSPOSE + key down) | `tr_m1.json` | transpose sign encoding |
| 6 | **MIDI channel → 2** | `ch2.json` | channel byte + offset (0- vs 1-based) |
| 7 | **MIDI channel → 16** | `ch16.json` | confirm channel range/encoding |
| 8 | **Arp ON** | `arp_on.json` | re-confirms `idx 4` |
| 9 | **Arp Mode → next** (hold ARP + mode key) | `arpmode.json` | arp-mode byte + enum order |
| 10 | **Time Division → next** (hold ARP + div key) | `timediv.json` | time-division byte + enum order |
| 11 | **Arp Octave → 2** (hold ARP + oct key) | `arpoct.json` | arp-octave byte |
| 12 | **Latch ON** | `latch.json` | latch byte |
| 13 | **Tempo → 200** | `tempo200.json` | tempo byte(s) — 1 byte or 2? (>127 ⇒ 2) |
| 14 | **Tempo → 60** | `tempo60.json` | confirm tempo encoding |
| 15 | **Tap count → 3** | `taps3.json` | tempo-taps byte |
| 16 | **Clock → External** | `clock_ext.json` | clock byte |

After each confirmed mapping, set `verified=True` (and fix the index/encoding if
needed) on that `Field` in `src/lpk25/codec.py`, and note the finding in
`docs/protocol.md`. When a field's encoding is nailed, add its before/after
payloads as a golden vector in `tests/test_codec.py`.

## After the map is complete

1. **Round-trip test** (Phase 1 gate): `get` → `set` the *same* bytes → `get`;
   confirm identical. Proves the write path is safe before trusting writes.
2. **First real write**: write `arp_enabled` (the one confirmed field), verify by
   re-read and by `lpk25 monitor`.
3. Open question: is there a separate **globals** payload, or only the 4 programs?

## Already evaluated, NOT useful (don't re-check)

Public repos `ahuertam/akai25`, `bencevans/lpk25-console`, `bencevans/lpk25.js`
are all note-input/Web-MIDI playing apps — none touch the editor SysEx protocol
(akai25 even requests `{ sysex: false }`). No protocol info there.
