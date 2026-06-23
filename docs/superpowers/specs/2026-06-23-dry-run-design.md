# LPK25 mk1 CLI — `--dry-run` Preview — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** `codec.diff_payloads` and the `diff` command's change rendering;
  the device read path. Tracks issue #9.

## Problem

The write commands (`set`, `load`, `edit`, `copy`, `preset apply`, `restore`)
change the device immediately. There's no way to preview exactly what a write
would change first. We already have the perfect primitive — `codec.diff_payloads`
— so a `--dry-run` that reads the current program(s), shows the field/byte diff,
and writes nothing is low-cost and high-confidence.

## Goal

`--dry-run` on any write command: read the affected slot(s), print the per-slot
field/byte diff of *current → would-be*, and exit without writing or backing up.

## Non-goals (YAGNI)

- An interactive "apply now?" prompt after the preview.
- Showing diffs for read-only commands (`dump`, `get`, `show`, `diff`, `identify`).
- Any change to `device.py`'s write/backup semantics.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Flag style | **global `--dry-run`** on the top parser | one implementation; consistent across every write command; read-only commands ignore it |
| Scope | **all write commands**: set, load, edit, copy, preset apply, restore | a preview everywhere a write happens |
| Where | **CLI preview helper** | no change to `device.py`; reuses the read path + `diff_payloads` |
| Baseline | current **on-device** program (a read), per target slot | shows the real change against live state |
| Output | per-slot field/byte diff, same rendering as `diff` | DRY: one shared change formatter |
| Side effects | **none** — no write, no backup; rc 0 | a preview must be safe |

## CLI surface

Add a global flag (next to `--mock`, `--model`):

```
lpk25 [--dry-run] <write-command> ...
```

Behaviour when `--dry-run` is set on a write command:
1. Build the target `Program`(s) the command would write.
2. For each, read the current slot from the device and
   `diff_payloads(current.raw, target.raw)`.
3. Print `slot N: K byte(s) would change` + one line per change (or
   `slot N: no change`).
4. Print `(dry run — nothing written)` and return 0. No backup, no send.
5. `copy`'s confirmation prompt is skipped under `--dry-run` (nothing is written
   to confirm).

Example:
```
$ lpk25 --dry-run edit 1 --tempo 120 --channel 5
slot 1: 3 byte(s) would change
  idx  1: 0x00 (0) -> 0x04 (4)    midi_channel [confirmed]
  idx 10: 0x00 (0) -> 0x00 (0)    tempo [confirmed]
  idx 11: 0x78 (120) -> 0x78 (120)  tempo [confirmed]

(dry run — nothing written)
```

## Architecture / components

```
src/lpk25/
  cli.py   + _format_change(c) -> str         (extracted from cmd_diff)
           + _preview(dev, programs) -> int    (read current, diff, print)
           + global --dry-run argument
           cmd_set/cmd_load/cmd_edit/cmd_copy/cmd_preset(apply)/cmd_restore:
             early `if args.dry_run: return _preview(dev, targets)`
  device.py  unchanged
```

### `_format_change(c)`

Extract the existing per-change line from `cmd_diff` into a helper so `diff` and
`_preview` render identically:

```python
def _format_change(c) -> str:
    old = "--" if c.old is None else f"0x{c.old:02X} ({c.old})"
    new = "--" if c.new is None else f"0x{c.new:02X} ({c.new})"
    label = c.field or "unmapped"
    mark = "confirmed" if c.verified else "unverified"
    return f"  idx {c.index:2d}: {old} -> {new}   {label} [{mark}]"
```

### `_preview(dev, programs)`

```python
def _preview(dev, programs) -> int:
    for prog in programs:
        current = dev.get_program(prog.slot)
        changes = codec.diff_payloads(current.raw, prog.to_payload())
        if not changes:
            print(f"slot {prog.slot}: no change")
            continue
        print(f"slot {prog.slot}: {len(changes)} byte(s) would change")
        for c in changes:
            print(_format_change(c))
    print("\n(dry run — nothing written)")
    return 0
```

### Per-command wiring

Each write command, after building its target program(s) and the device but
**before** any backup/write, returns early when `args.dry_run`:

| Command | Targets passed to `_preview` |
|---------|------------------------------|
| `set` | `[program]` (from file, slot set) |
| `load` | `preset.programs` |
| `edit` | `[patched]` (already built from the read-back `before`) |
| `copy` | `[src.reslot(d) for d in dsts]` (skip the confirm prompt) |
| `preset apply` | `[prog.reslot(slot)]` |
| `restore` | `Preset.load(file).programs` |

## Error handling / edge cases

| Case | Behaviour |
|------|-----------|
| slot unreadable / no device reply | `DeviceError` bubbles to the top handler → rc 1 (can't preview what we can't read) |
| target identical to current | `slot N: no change`; still rc 0 |
| `--dry-run` on a read-only command | flag ignored (those commands never branch on it) |
| `--mock` + `--dry-run` | previews against the mock's stored programs |

## Testing (all via `MockTransport`, no hardware)

- `_format_change` / `_preview`: a changed program prints the right slot header +
  change lines and writes nothing (mock `.sent` stays empty).
- Each write command under `--dry-run`: `edit`, `set`, `load`, `copy`,
  `preset apply`, `restore` print a diff and leave `MockTransport.programs`
  unchanged and `.sent` empty (no `OP_SEND_PROGRAM`).
- `copy --dry-run` does not prompt (no `input()`).
- no-op case: identical target prints `no change`.

## Documentation

- Add `--dry-run` to the README usage notes.
- Issue #9 closed by the implementing PR.
