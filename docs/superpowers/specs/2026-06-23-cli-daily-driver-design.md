# LPK25 mk1 CLI — Daily-Driver Polish — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation plan
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** `2026-06-22-lpk25-mk1-editor-design.md` (Phase 3 polish)

## Problem

The protocol is reverse-engineered and the library/CLI can read, write, diff,
back up, and restore the device (12 of 13 program bytes confirmed on real
hardware, write path validated). But day-to-day use is still awkward: changing
one setting means hand-editing a JSON file and running `set`; there is no quick
way to see how the device is configured; and there is no notion of a named,
reusable preset. This phase makes the CLI a comfortable daily driver.

## Goals (the three things the user wants)

1. **Quick single tweaks** — change one or more parameters from the command line
   without editing JSON.
2. **Named single-program preset library** — save a config under a name and
   apply it to any slot on demand.
3. **Glanceable state** — a human-readable readout of what is on the device.

## Non-goals (YAGNI)

- Copy/duplicate slots (explicitly deprioritized by the user).
- Whole-device 4-slot snapshots — `backup`/`restore` already cover that.
- Interactive TUI editor — Phase 4 / GUI territory.
- `preset rm` / `preset show` — easy to add later if wanted; not in v1.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Approach | Thin subcommands over the existing library | Reuses validated `device.py` safety (backup + read-back verify); minimal new code; fits library-first design. |
| Preset granularity | **One program/config** per named preset | Matches the official editor's "preset"; flexible (apply to any slot). |
| Edit target | Operate **directly on the device** | The device is the thing being configured; round-trip through files is the existing `get`/`set` flow. |
| Preset file format | Existing single-program `Preset`/`Program` JSON | Interoperable with `get -o` / `set`; no new format. |
| Overwrite policy | `preset save` refuses to clobber unless `--force` | Named presets are precious; avoid silent loss. |

## CLI surface (new commands)

### `lpk25 edit <slot> [field flags] [--no-verify]`

Reads slot `<slot>` (1–4), patches only the named fields onto the preserved raw
payload, writes it back via `device.send_program()` (auto-backup + read-back
verify), then prints a diff of what changed (reusing `codec.diff_payloads`).

Field flags (one per parameter; all optional):

| Flag | Field | Accepts |
|------|-------|---------|
| `--channel` | midi_channel | 1–16 |
| `--octave` | keybed_octave | −4…4 |
| `--transpose` | transpose | −12…12 |
| `--arp` | arp_enabled | `on`/`off` |
| `--arp-mode` | arp_mode | up, down, inclusive, exclusive, order, random |
| `--time-div` | time_division | 1/4, 1/4T, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T |
| `--clock` | clock | internal, external |
| `--latch` | arp_latch | `on`/`off` |
| `--tempo` | tempo | 30–240 |
| `--taps` | tempo_taps | 2, 3, 4 (note: by-elimination field; printed caveat) |
| `--arp-octave` | arp_octave | 0–3 |

- No field flags → error: "nothing to change".
- Out-of-range / unknown value → error before any device write (no partial write).
- Example: `lpk25 edit 1 --channel 5 --octave -1 --tempo 120 --arp on`

### `lpk25 show [slot] [--json]`

- No slot: read all 4 programs (+ active slot), print a table, one row per slot,
  with a `▶` marker on the active program.
- With slot: a compact vertical field list for that one slot.
- `--json`: defer to the existing `dump` JSON output.

Example table:

```
slot  ch  oct  trans  arp  mode   div    clock  latch  tempo  taps  aoct
 ▶1    5   -1     0    on   up     1/8    int    off    120     3     0
  2    1    0     0    off  up     1/4    int    off    120     3     0
  3   …
```

### `lpk25 preset save|apply|list`

- `lpk25 preset save <name> [--from-slot N] [--force]` — read slot `N` (default 1),
  save as `<preset-dir>/<name>.json` (single-program `Preset`). Refuse if the file
  exists unless `--force`.
- `lpk25 preset apply <name> <slot>` — load `<name>.json`, write its program onto
  `<slot>` via `device.send_program()` (backup + verify).
- `lpk25 preset list` — list saved preset names, each with a one-line summary
  (channel/octave/arp/tempo).

## Architecture (new modules, kept small and pure)

```
src/lpk25/
  library.py   NEW — preset-directory resolution + file ops (no device, pure)
  render.py    NEW — human-readable formatting (pure functions -> str)
  cli.py       +3 commands (edit, show, preset) wiring the above to device.py
  codec.py     reused (encode/decode/diff, enum label sets) — no change
  device.py    reused (send_program backup+verify, dump, get) — no change
  model.py     reused (Preset/Program JSON) — no change
```

### `library.py` (pure, unit-testable without hardware)

- `preset_dir() -> str` — `$LPK25_PRESET_DIR` → `$XDG_CONFIG_HOME/lpk25/presets`
  → `~/.config/lpk25/presets`. Does not create the dir on read.
- `save_preset(name, program, force=False) -> str` — writes a single-program
  `Preset` JSON; creates the dir; raises if it exists and not `force`.
- `load_preset(name) -> Program` — reads `<name>.json`, returns its first program;
  raises a clear error (with available names) if missing.
- `list_presets() -> list[tuple[name, Program]]` — names + decoded program for
  summaries.

### `render.py` (pure)

- `format_presets_table(preset, active_slot=None) -> str`
- `format_program(program) -> str`
- Pulls display values from `codec.decode_program` (so it shows the same labels
  the CLI accepts). Golden-string tested.

### `cli.py`

- `FLAG_TO_FIELD`: a table mapping each `--flag` to `(codec field name, parser)`,
  where enum parsers reuse `codec.ARP_MODES` / `TIME_DIVISIONS` / `CLOCK_SOURCES`
  so flag choices and device codes cannot drift.
- `cmd_edit`, `cmd_show`, `cmd_preset` (with `save`/`apply`/`list` subparsers).

## Data flow

- **edit:** parse flags → values dict → `device.get_program(slot)` →
  `codec.encode_program(values, raw)` → `device.send_program` (backup+verify) →
  print `diff_payloads(before, after)`.
- **show:** `device.dump()` + `device.get_active_program()` →
  `render.format_presets_table`.
- **preset save:** `device.get_program(slot)` → `library.save_preset`.
- **preset apply:** `library.load_preset(name)` → set slot →
  `device.send_program` (backup+verify).

## Error handling

| Case | Behavior |
|------|----------|
| Bad field value (`--channel 99`, `--arp-mode wat`) | Friendly error; no device write. |
| `edit` with no field flags | Error: "nothing to change". |
| `preset apply <missing>` | Error listing available preset names. |
| `preset save` onto existing name | Refuse unless `--force`. |
| `--taps` (tempo_taps) | Works; one-line note that idx 9 is by-elimination/unverified. |
| Device write fails read-back verify | Existing `VerificationError` from `device.py` (with sent vs got hex). |

## Testing (all via `MockTransport`, no hardware)

- `library.py`: dir resolution (env override, XDG, default), save/list/load
  round-trip, overwrite-guard (raises without `--force`).
- `render.py`: golden-string table for a known 4-preset set; active marker.
- `edit`: each flag maps to the correct codec field; multi-flag patch changes
  only those bytes; out-of-range value rejected before write.
- `preset apply`: writes the saved program to the chosen slot on the mock.
- Existing 36 tests continue to pass (no core changes).

## Documentation

- Update `README.md` and `docs/feature-list.md` CLI surface tables with `edit`,
  `show`, and `preset save/apply/list`; mark copy-slot and `.syx` export as the
  remaining ⬜ items.
