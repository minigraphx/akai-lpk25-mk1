# LPK25 mk1 editor — feature list

Derived from the official **LPK25 Quickstart Guide (Rev B)**, **LPK25 Editor
User Guide v1.0**, and the device's **MIDI Implementation Chart**
(Model: LPK25, Version 1.0, 2009-05-15).

Status legend: ✅ done · 🟡 partial / provisional · ⬜ to do

## 1. Program / preset data model (full editor parity)

Each of the **4 presets** holds these editable parameters:

| # | Parameter | Range / values | Status |
|---|-----------|----------------|--------|
| 1 | MIDI channel | 1–16 | ✅ idx 1, `byte+1` (wrote ch10 → keys on ch10) |
| 2 | Transposition | −12 … +12 semitones | ✅ idx 3, `byte−12` (wrote +12 → notes +12) |
| 3 | Octave (preset default) | −4 … +4 | ✅ idx 2, `byte−4` |
| 4 | Arp octave (range) | **0–3** | ✅ idx 12, direct |
| 5 | Arp enable | on / off | ✅ idx 4 |
| 6 | Arp mode | Up, Down, Inclusive, Exclusive, Order, Random | ✅ idx 5 (codes = editor order, Up=0 Excl=3) |
| 7 | Arp time division | 1/4, 1/4T, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T | ✅ idx 6, 0…7 |
| 8 | Arp clock | internal / external | ✅ idx 7 (`1`=external stalled the arp) |
| 9 | Arp latch | on / off | ✅ idx 8 (`1` → arp ran after release) |
| 10 | Tap-tempo taps | 2 / 3 / 4 | ✅ idx 9 (taps=2 → 2 taps set tempo; taps=4 → 2 ignored, 4 worked) |
| 11 | Tempo | 30–240 BPM (2 bytes on device) | ✅ idx 10–11, 14-bit `(hi<<7)\|lo` |

**All 13 program bytes confirmed on real hardware (2026-06-23).** See
`docs/protocol.md` for the full byte map.

## 2. Device operations (talk to the LPK25)

| Feature | Editor equivalent | Status |
|---------|-------------------|--------|
| Read one preset (1–4) from device | GET PRESET | ✅ (`get`) framing confirmed on hardware |
| Read all 4 presets | — | ✅ (`dump`) |
| Write/upload one preset to a slot | COMMIT – UPLOAD | ✅ (`set`) round-trip byte-exact + read-back verify |
| Write all 4 presets | — | 🟡 (`load`) — same path as `set`, not yet exercised on all 4 |
| Choose target slot (PRESET #) | EDIT PRESET field | ✅ (slot arg) |
| Edit single fields on a slot | (inline, no editor) | ✅ (`edit`) |
| Interactive multi-field editor | full editor screen | ✅ (`tui`) |
| Human-readable state readout | — | ✅ (`show`) |
| Named single-program preset library | SAVE/LOAD PRESET | ✅ (`preset save/apply/list`) |
| Copy preset (read slot A → write slot B) | copy workflow | ✅ (`copy`, one or more dsts) |
| Recall/activate a preset on device | (hardware PROGRAM + PROG key) | ✅ (`activate <slot>`) |

## 3. File operations (computer-side)

| Feature | Editor equivalent | Status |
|---------|-------------------|--------|
| Save preset to file | SAVE PRESET | ✅ (JSON) |
| Load preset from file | LOAD PRESET | ✅ (JSON) |
| Save/restore all 4 + backup | — | ✅ (`backup`/`restore`) |
| `.syx` import/export (structured, interoperable) | — | ✅ (`convert`; `.syx` extension in get/dump/set/load) |
| Human-editable format | — | ✅ (JSON) |

## 4. Discovery & reverse-engineering (mk1-specific)

| Feature | Status |
|---------|--------|
| List/auto-detect MIDI ports | ✅ (`ports`) |
| MIDI setup & device self-diagnostic | ✅ (`doctor`): ordered checks backend → ports → device → optional write round-trip; ✅/❌ + fix hint per step; `--roundtrip` opt-in write test; non-zero exit on failure |
| Probe candidate model bytes (read-only) | ✅ (`identify` → probe) |
| Universal Device Inquiry | ✅ **supported** — real hardware answers it (family LSB = model `0x76`), contradicting the MIDI chart; confirms model + probe agree |
| Capture raw MIDI/SysEx to file | ✅ (`raw-recv`) |
| Replay captured SysEx | ✅ (`raw-send`) |
| Live MIDI monitor (behavioural oracle) | ✅ (`monitor`) |
| Round-trip integrity check (read→write same→read) | ✅ confirmed on hardware (byte-exact + read-back verify) |
| **Hardware-assisted field mapping** | ✅ done — all panel params mapped via change-one-setting-and-`diff`; editor-only fields confirmed via write + behavioural oracle |

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
| Unit tests (codec/protocol/model/mock/cli) | ✅ |
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
*transmit* (it only *receives* external clock), GM/DLS.

(The MIDI chart also lists **Device Inquiry** as unsupported, but real hardware
*does* answer it — see section 4 and `docs/protocol.md`.)
