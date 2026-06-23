# LPK25 mk1 CLI — Decoded MIDI Monitor — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** the existing `monitor` command and `Transport.monitor()` hook;
  adds a new pure-parsing module. Tracks issue #5.

## Problem

`lpk25 monitor` prints raw hex frames (`cmd_monitor` in `cli.py`). For the
behavioural-oracle workflow (confirming what a program actually does when you
play keys) and for general debugging, a human-readable decode — note names,
velocity, channel, CC, transport messages — is far more useful than hex.

## Goal

Decode each incoming MIDI message into a concise, readable line by default,
while keeping the raw bytes one flag away and the view uncluttered.

## Non-goals (YAGNI)

- Decoding in `raw-recv` — that command captures bytes to a `.syx` file and stays
  byte-faithful (always hex).
- Per-channel filtering (`--channel N`) or message-type include/exclude lists —
  revisit only if needed.
- Writing a captured/annotated log to file (monitor is a live view).
- A full MIDI-spec pretty-printer (SMF meta events, etc.) — we decode live wire
  messages only.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Default mode | **decoded**, `--raw` to opt out | readable by default; bytes one flag away |
| Coverage | **full general MIDI**; unknown → hex | useful general tool; never hides traffic |
| Noise | **hide Active Sensing (0xFE) + Clock (0xF8) by default**, `--all` shows | keyboards/ports flood these; keep signal visible. Start/Continue/Stop stay shown (arp-relevant) |
| Timestamps | **`--timestamps`** opt-in, relative seconds | handy for arp/tempo timing; off by default for clean output |
| Octave naming | scientific pitch: MIDI 60 = `C4`, A4 = 440 Hz | unambiguous, anchored on A440 |
| Note On vel 0 | render as **Note Off** | standard MIDI convention |
| `raw-recv` | **unchanged** | capture stays byte-faithful |

## CLI surface

### `lpk25 monitor [--seconds N] [--raw] [--all] [--timestamps]`

- `--seconds N`: existing; how long to listen (default 30).
- `--raw`: print hex bytes instead of the decode (the old behaviour).
- `--all`: also show Active Sensing and Clock (hidden by default).
- `--timestamps`: prefix each line with a relative `[   s.sss]` offset from the
  first message.

`--raw`, `--all`, and `--timestamps` compose: filtering and timestamps apply in
both decoded and raw modes; `--raw` only swaps the message body (hex vs decode).

Example session (decoded, default):
```
$ lpk25 monitor
Monitoring MIDI input for 30s. Play the keyboard... (Ctrl-C to stop)
ch1 Note On  C4 vel 100
ch1 Note Off C4 vel 0
ch1 CC 64 (Sustain) = 127
```
With `--timestamps`:
```
[   0.000] ch1 Note On  C4 vel 100
[   0.214] ch1 Note Off C4 vel 0
```

## Architecture / components

```
src/lpk25/
  mididecode.py   NEW — pure MIDI-message parsing (no deps, fully unit-testable)
  cli.py          cmd_monitor: apply filter + optional timestamp + body;
                  add --raw/--all/--timestamps to the monitor subparser
```

Keep all parsing in `mididecode.py` so it is testable without hardware. The
monitor loop stays a thin wrapper: decide whether to skip the frame (filter),
format the body (decode or hex), and optionally prefix a timestamp.

### `mididecode.py` API

```python
def note_name(note: int) -> str: ...
    # 60 -> "C4", 69 -> "A4"

def decode_message(frame: bytes) -> str: ...
    # one-line description; falls back to a hex dump for anything malformed

def is_noise(frame: bytes) -> bool: ...
    # True for Active Sensing (0xFE) and Clock (0xF8) — hidden unless --all

def format_line(frame: bytes, *, raw: bool, t: float | None) -> str: ...
    # composes optional "[   t]" prefix + (hex if raw else decode)
```

`format_line` makes the whole per-line output testable end-to-end (the live
`monitor` loop itself needs hardware, but the formatting does not).

### Decoding coverage

| Status | Rendered as |
|--------|-------------|
| 0x8n / 0x9n (note off / on) | `chN Note On/Off <name> vel V` (0x9n vel 0 → Note Off) |
| 0xAn poly aftertouch | `chN Poly Pressure <name> V` |
| 0xBn control change | `chN CC <n> [(name)] = V` (label common CCs, e.g. 64 Sustain) |
| 0xCn program change | `chN Program Change n` |
| 0xDn channel pressure | `chN Channel Pressure V` |
| 0xEn pitch bend | `chN Pitch Bend ±N` (14-bit, centred at 0) |
| 0xF0 SysEx | `SysEx (<mfr>), N bytes: F0 …` (label Akai / Universal) |
| 0xF1/F2/F3 system common | MTC quarter frame / Song Position / Song Select |
| 0xF6/F8/FA/FB/FC/FE/FF | Tune Request / Clock / Start / Continue / Stop / Active Sensing / Reset |
| anything else / truncated | hex fallback |

## Error handling / edge cases

| Case | Behaviour |
|------|-----------|
| empty frame | `(empty)` |
| truncated channel message (missing data bytes) | hex fallback (never crash) |
| transport without `monitor` (e.g. `--mock`) | existing message: "does not support monitoring", rc 2 |
| Ctrl-C | stop cleanly (existing behaviour) |

## Testing (all offline, no hardware)

- **mididecode:** table-driven cases for every status class above — note on/off,
  vel-0-as-off, CC with/without a known label, program change, pitch bend
  (negative/zero/positive), channel/poly pressure, SysEx (Akai + Universal),
  clock/start/stop/active-sensing, song position/select, empty, and a truncated
  message → hex fallback.
- **note_name:** 0 → `C-1`, 60 → `C4`, 69 → `A4`, 127 → `G9`.
- **is_noise:** True for 0xFE/0xF8, False for notes/Start/Stop.
- **format_line:** raw vs decoded body; timestamp prefix formatting; filter not
  applied here (caller decides) — or include a small monitor-loop helper test.

## Documentation

- Update the README `monitor` usage to mention `--raw`, `--all`, `--timestamps`.
- Issue #5 closed by the implementing PR.
- (`docs/feature-list.md` already lists the monitor as ✅; optionally note the
  decoded view.)
