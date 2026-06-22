# LPK25 mk1 editor — feature list

Derived from the official **LPK25 Quickstart Guide (Rev B)**, **LPK25 Editor
User Guide v1.0**, and the device's **MIDI Implementation Chart**
(Model: LPK25, Version 1.0, 2009-05-15).

Status legend: ✅ done · 🟡 partial / provisional · ⬜ to do

## 1. Program / preset data model (full editor parity)

Each of the **4 presets** holds these editable parameters:

| # | Parameter | Range / values | Status |
|---|-----------|----------------|--------|
| 1 | MIDI channel | 1–16 | 🟡 codec field (provisional offset) |
| 2 | Transposition | −12 … +12 semitones | 🟡 |
| 3 | Octave (preset default) | −4 … +4 | 🟡 |
| 4 | Arp octave (range) | **0–3** | 🟡 (corrected from 1–4) |
| 5 | Arp enable | on / off | 🟡 |
| 6 | Arp mode | Up, Down, Inclusive, Exclusive, Order, Random | 🟡 (byte order TBD) |
| 7 | Arp time division | 1/4, 1/4T, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T | 🟡 |
| 8 | Arp clock | internal / external | 🟡 |
| 9 | Arp latch | on / off | 🟡 |
| 10 | Tap-tempo taps | 2 / 3 / 4 | 🟡 |
| 11 | Tempo | 30–240 BPM (likely 2 bytes on device) | 🟡 |

All "🟡" become "✅" once the byte layout is confirmed against hardware.

## 2. Device operations (talk to the LPK25)

| Feature | Editor equivalent | Status |
|---------|-------------------|--------|
| Read one preset (1–4) from device | GET PRESET | 🟡 (`get`) needs real framing confirmed |
| Read all 4 presets | — | 🟡 (`dump`) |
| Write/upload one preset to a slot | COMMIT – UPLOAD | 🟡 (`set`) |
| Write all 4 presets | — | 🟡 (`load`) |
| Choose target slot (PRESET #) | EDIT PRESET field | ✅ (slot arg) |
| Copy preset (read slot A → write slot B) | copy workflow | ⬜ (compose get + set) |
| Recall/activate a preset on device | (hardware PROGRAM + PROG key) | 🟡 (`activate` builder exists, no CLI cmd) |

## 3. File operations (computer-side)

| Feature | Editor equivalent | Status |
|---------|-------------------|--------|
| Save preset to file | SAVE PRESET | ✅ (JSON) |
| Load preset from file | LOAD PRESET | ✅ (JSON) |
| Save/restore all 4 + backup | — | ✅ (`backup`/`restore`) |
| `.syx` import/export (raw, interoperable) | — | ⬜ (`raw-send` exists; structured `.syx` export ⬜) |
| Human-editable format | — | ✅ (JSON) |

## 4. Discovery & reverse-engineering (mk1-specific)

| Feature | Status |
|---------|--------|
| List/auto-detect MIDI ports | ✅ (`ports`) |
| Probe candidate model bytes (read-only) | ✅ (`identify` → probe) |
| ~~Universal Device Inquiry~~ | ❌ **not supported by device** (per MIDI chart) — probing is primary |
| Capture raw MIDI/SysEx to file | ✅ (`raw-recv`) |
| Replay captured SysEx | ✅ (`raw-send`) |
| Live MIDI monitor (behavioural oracle) | ✅ (`monitor`) |
| Round-trip integrity check (read→write same→read) | ✅ (verified via `set` read-back) |
| **Hardware-assisted field mapping** | ⬜ guide: set Time Div / Arp Mode / Arp Octave on the device (hold ARP ON/OFF + labeled key), then `dump` to see which byte changed |

## 5. Safety

| Feature | Status |
|---------|--------|
| Auto-backup before any write | ✅ |
| Read-back verify after write | ✅ |
| Preserve unknown raw bytes (byte-exact round trip) | ✅ |
| Rate limiting (flash protection) | ✅ |
| Restore from backup | ✅ |
| Document factory reset / recovery | ⬜ |

## 6. Quality / packaging / cross-platform

| Feature | Status |
|---------|--------|
| Pure-Python core, unit-testable without hardware | ✅ |
| Unit tests (codec/protocol/model/mock) | ✅ (22) |
| Lint (ruff) | ✅ |
| CI (ruff + pytest, 3.9 & 3.12) | ✅ |
| Linux support | ✅ (primary dev target) |
| macOS support | 🟡 (same code; needs a validation pass before release) |
| Windows support | 🟡 (incidental; not a goal) |
| Packaging / installable release | ⬜ |

## 7. Future (post-CLI)

| Feature | Status |
|---------|--------|
| GUI editor (visual, like the original) | ⬜ (Phase 4) |
| Preset library/sharing | ⬜ |

## Hardware controls (reference — handled by the device, not us)

25 velocity-sensitive keys (9-octave range) · OCTAVE −/+ (±4, both = reset) ·
ARP ON/OFF · TAP TEMPO · SUSTAIN/LATCH · PROGRAM + PROG 1–4 (recall preset) ·
hold ARP ON/OFF + labeled key to set Time Division / Arp Mode / Arp Octave.

## Not supported by the device (per MIDI chart)

Program Change, Bank Select, Pitch Bend, Aftertouch, NRPN/RPN, MIDI Clock
*transmit* (it only *receives* external clock), Device Inquiry, GM/DLS.
