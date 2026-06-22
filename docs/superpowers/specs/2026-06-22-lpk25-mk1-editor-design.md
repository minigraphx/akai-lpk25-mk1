# LPK25 mk1 Editor — Design

- **Date:** 2026-06-22
- **Status:** Approved (design discussion); implementation in progress
- **Author:** drafted collaboratively via the brainstorming method

## Problem

There is no program editor for the **Akai LPK25 mk1** on macOS or Linux. The
official editor ships only for Windows and legacy macOS. Owners on modern
macOS/Linux therefore cannot re-program the device's four stored programs.

We want cross-platform software that can read, edit, back up, and write the
LPK25 mk1's programs, with full parity to the official editor's feature set.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Form factor | **CLI core + protocol library first, GUI later** | De-risk the protocol before investing in UI; library is reusable by any future GUI. |
| Language/stack | **Python** | Easiest for byte-level reverse engineering, good MIDI libs (`mido` + `python-rtmidi`), cross-platform, matches the existing MK2 reference project. |
| Protocol acquisition | **Derive from MK2 + probe** | No access to the official editor to capture from, so we derive a candidate protocol and verify it empirically against the device. |
| Scope (v1) | **Full editor parity** | All 4 programs, every documented parameter, Get/Send to device, Save/Open files. |
| Test hardware | **User's Linux machine** | The device is attached to the user's box, not the dev environment, so the user runs hardware tests; the codebase is structured to unit-test everything else without hardware. |

## The core challenge

The mk1's **model ID, opcodes, and exact program byte-layout are unknown** —
they are not publicly documented and we cannot capture the official editor.

We derive a *candidate* protocol from the well-documented MK2
(`lpk25-linux` project) and verify it against the real device using two safe
oracles:

1. **Round-trip integrity** — read a program, write the *same bytes* back, read
   again, confirm identical. Proves framing/read/write are correct *before* we
   understand any byte's meaning.
2. **Behavioral oracle** — the LPK25's own MIDI output. After writing a
   candidate program (e.g. MIDI channel = 5), play a key; the tool listens to
   the keyboard's output and confirms the note arrived on channel 5. Octave and
   transpose are confirmed via note numbers, arp mode via note ordering, tempo
   via timing, etc. The device tells us what each byte means.

### Reference: mk1-family protocol (primary hypothesis)

The strongest reference is the **Akai LPD8 mk1** — the same generation/family as
the LPK25 mk1 — whose protocol is fully reverse-engineered (`lpd8editor`):

- Frame: `F0 47 7F <model> <op> <len_hi> <len_lo> [data] F7`.
- `47` = Akai manufacturer; `7F` = broadcast device id.
- Model byte: LPD8 = `0x75`. **The LPK25 mk1 model byte is the main unknown**
  (expected adjacent, e.g. `0x76`/`0x77`); the Universal Device Inquiry should
  reveal it directly.
- Length = 16-bit big-endian, immediately after the opcode.
- Opcodes are consistent across the family:
  `0x63` get program → response same opcode; `0x61` send program (no ack);
  `0x62` activate program; `0x64` get active program.
- **Program payload is LPK25-specific.** Unlike the LPD8 (pads + knobs), the
  LPK25 program carries keybed + arpeggiator settings. Its exact byte layout and
  length are TBD, learned from the first real dump (the length field tells us the
  size). Field *ordering* hypothesis is taken from the MK2 (channel, octave,
  transpose, latch, mode, time-div, arp-on, tempo-taps, clock, tempo, arp-octave)
  minus swing.

Secondary reference: the **LPK25 MK2** (`lpk25-linux`) — same opcode semantics,
different framing (`F0 47 <dev> 4D …`) and a 14-byte program including swing.

These are *hypotheses*, not facts, for the mk1. The implementation treats the
model byte, opcodes, and field layout as **adjustable configuration/data**, so
discovery findings are a data change, not a rewrite.

## Safety model (non-negotiable — we are probing real hardware)

- **Auto-backup** all 4 programs (+ globals) to a timestamped file before *any*
  write.
- **Read-back verify** after every write; report a diff if the device's stored
  bytes don't match what we sent.
- **Reads are always safe.** Writes are gated behind backup + explicit
  confirmation.
- **Raw-byte preservation:** decoded programs retain the full raw payload, and
  encoding patches only known fields back into that payload. Bytes we don't
  understand are never lost, so round-trip writes are byte-exact even with an
  incomplete field map.
- **Rate limiting:** ≤16 frames/batch, ≥80 ms between frames, ≥300 ms between
  batches, to protect the device's flash.
- `restore` from backup + documented factory-reset as escape hatches.

## Architecture (library-first)

```
src/lpk25/
  transport.py   MIDI I/O (mido + python-rtmidi, lazily imported) + MockTransport
  protocol.py    SysEx frame build/parse; model-id & opcodes as adjustable config
  codec.py       Program/Globals <-> bytes via a declarative, provisional field table
  model.py       Program/Globals/Preset dataclasses + range validation + JSON
  discovery.py   Universal Device Inquiry + candidate probing helpers
  device.py      high-level ops: identify, dump, get, set(+backup+verify), load, restore
  cli.py         the `lpk25` command
tests/           framing, codec round-trips, mock-device ops, golden byte vectors
docs/protocol.md evolving clean-room mk1 protocol notes (credits MK2 reference)
```

- `protocol`, `codec`, and `model` have **zero external dependencies** and are
  fully unit-testable in CI / the dev environment without hardware.
- `transport` imports the MIDI backend lazily so `import lpk25` and all unit
  tests work even when `python-rtmidi` isn't built. A `MockTransport` provides a
  scriptable in-memory device for tests.
- A future GUI sits on top of `device.py` unchanged.

## Data model & file formats

**Program parameters** (from the official LPK25 Editor user guide):

| Parameter | Range |
|-----------|-------|
| MIDI channel | 1–16 |
| Keybed octave | −4 … +4 |
| Transpose | −12 … +12 semitones |
| Arpeggiator | On / Off |
| Latch | On / Off |
| Arp mode | Up, Down, Exclusive, Inclusive, Order, Random |
| Clock | Internal / External |
| Tempo | 30–240 BPM |
| Tempo taps | 2 / 3 / 4 |
| Time division | 1/4, 1/4T, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T |
| Arp octave | 1 / 2 / 3 / 4 |

(No swing — the mk1 lacks it.)

- **Preset** = the 4 programs (+ optional globals).
- **Primary format: JSON** — human-readable, diffable, hand-editable for CLI use.
- **Also: `.syx`** import/export — raw frames, interoperable with other MIDI
  tools and exact device replay.

## CLI surface (full parity + discovery + safety)

| Command | Purpose |
|---------|---------|
| `lpk25 ports` | List MIDI ports; auto-detect the LPK25. |
| `lpk25 identify` | Universal Device Inquiry + protocol probe; print findings. |
| `lpk25 monitor` | Listen to the keyboard's live MIDI output (the behavioral oracle). |
| `lpk25 dump [-o file.json]` | Read all 4 programs (+ globals). |
| `lpk25 get <slot> [-o prog.json]` | Read one program. |
| `lpk25 set <slot> <file>` | Write one program (auto-backup + read-back verify). |
| `lpk25 load <preset.json>` | Write all 4 programs. |
| `lpk25 backup [-o file]` / `lpk25 restore <file>` | Safety net. |
| `lpk25 raw-recv` / `lpk25 raw-send <file.syx>` | Low-level capture/replay for discovery. |

## Phased plan

- **Phase 0 — Skeleton + safe discovery:** package scaffold, transport, frame
  codec, `ports` / `identify` / `monitor` / `raw-recv` / `raw-send`. Goal:
  identify the device and safely capture real replies (read-only).
- **Phase 1 — Read path:** decode dumps into the model, `dump` / `get`, JSON
  output, round-trip integrity test.
- **Phase 2 — Write path + semantics:** `set` / `load` / `backup` / `restore`
  with backup + read-back verify; map every field via the behavioral oracle;
  finalize `docs/protocol.md`.
- **Phase 3 — Polish:** full parity, `.syx` I/O, validation, docs, tests.
- **Phase 4 (later):** GUI on top of the library (Qt/Toga or a Web-MIDI
  frontend — decided later).

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| mk1 frame/opcodes differ from MK2 | Adjustable protocol config; `identify`/`raw-recv` to learn them empirically. |
| Wrong field map corrupts a program | Auto-backup, raw-byte preservation, read-back verify, restore. |
| Tempo (30–240) exceeds 7 bits | Treat as provisional multi-byte; preserved in raw until confirmed. |
| Can't test hardware in dev env | Unit-test codec/protocol/model with golden vectors + MockTransport; user runs device tests. |
| Iteration cost with user-in-the-loop | Data-driven protocol/field table keeps each iteration a small config change. |

## Out of scope (v1)

- GUI (Phase 4).
- Firmware updates.
- Non-mk1 hardware (MK2 already has `lpk25-linux`).
