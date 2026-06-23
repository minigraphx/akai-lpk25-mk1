# LPK25 mk1 CLI — `copy` Command — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation plan
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** the daily-driver CLI (`edit`/`show`/`preset`) and the confirmed
  protocol; reuses `device.load()` and the slot-echo correction from `preset apply`.

## Problem

There is no quick way to duplicate a program from one slot to another (or to
several). Today you'd `get` a slot to a file and `set` it onto each other slot by
hand. A `copy` command makes slot-to-slot duplication a single, safe step.

## Goal

`lpk25 copy <src> <dst...>` — copy the program in `src` onto one or more
destination slots, with a confirmation prompt and the usual auto-backup +
read-back verification.

## Non-goals (YAGNI)

- Cross-device or file-to-slot copy (that's `get`/`set`/`preset`).
- A separate "mirror to all" flag — `copy 1 2 3 4` already mirrors.
- Changing `device.py`'s write/backup semantics.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Destinations | one or more (`<dst...>`) | mirror in one call: `copy 1 2 3 4`. |
| Safety | **confirm, then auto-backup** | overwriting several slots warrants a prompt; `--yes` bypasses for scripts. |
| Implementation | reuse `device.load()` + a shared `Program.reslot()` | `load()` already does backup-once + rate-limit + per-slot verify; `reslot` removes duplicated slot-echo logic. |

## CLI surface

### `lpk25 copy <src> <dst...> [--yes] [--no-verify]`

- `src`: source slot, 1–4.
- `dst...`: one or more destination slots, each 1–4.
- `--yes` / `-y`: skip the confirmation prompt.
- `--no-verify`: skip read-back verification (consistent with `set`/`edit`).

Flow:
1. Read the `src` program (`dev.get_program(src)`).
2. Build the destination set: dedupe, and **drop `src`** if present (a slot can't
   copy onto itself). Print a note when `src` is dropped. If the set is then
   empty (e.g. `copy 1 1`), error `nothing to copy (destination is the source)`
   and return 2.
3. **Confirm** (unless `--yes`): print
   `About to overwrite slot(s) 2, 3 with a copy of slot 1. Proceed? [y/N]`
   and read stdin. Proceed only on `y`/`yes` (case-insensitive). Otherwise print
   `aborted; nothing written` and return 1 — no device write.
4. Build `Preset([src_prog.reslot(d) for d in dsts])` and call
   `dev.load(preset, verify=not args.no_verify)`. `load()` takes one timestamped
   backup of all 4 slots, writes each destination with rate-limiting, and
   read-back-verifies each.
5. Print each `slot N: verified=…` and the backup path.

Examples:
```
lpk25 copy 1 3            # copy slot 1 onto slot 3 (asks to confirm)
lpk25 copy 1 2 3 4 --yes  # mirror slot 1 onto 2,3,4, no prompt
```

## Architecture / components

```
src/lpk25/
  model.py   + Program.reslot(dst) — copy with slot-echo byte corrected
  cli.py     + cmd_copy, + _confirm() helper, + copy subparser;
             refactor cmd_preset apply to use Program.reslot()
  device.py  unchanged (load / send_program reused)
```

### `model.Program.reslot(dst: int) -> Program`

Returns a new `Program` whose payload is the source payload with byte 0 (the
slot echo) set to `dst`, `.slot` set to `dst`, and `.values` re-decoded from the
new payload. Raises `ValueError` if the program has no raw payload. This is the
single home for the slot-echo correction the device requires (the device echoes
the target slot in byte 0, so a cross-slot write must rewrite it or read-back
verify fails).

```python
def reslot(self, dst: int) -> "Program":
    if not self.raw:
        raise ValueError("cannot reslot a program with no raw payload")
    return Program.from_payload(dst, bytes([dst]) + self.raw[1:])
```

### `cli.cmd_copy` and `_confirm`

`_confirm(prompt) -> bool` wraps `input()` and returns True for `y`/`yes`
(case-insensitive). `cmd_copy` parses args, computes the cleaned destination
list, calls `_confirm` unless `--yes`, then builds the `Preset` and calls
`dev.load()`.

### Refactor: `cmd_preset apply`

Replace its inline
`Program.from_payload(args.slot, bytes([args.slot]) + prog.raw[1:])`
with `prog.reslot(args.slot)` — same behavior, no duplicated echo logic.

## Data flow

`get_program(src)` → `reslot(d)` per dst → `Preset(programs)` →
`dev.load(preset)` (backup once → write+verify each).

## Error handling

| Case | Behavior |
|------|----------|
| `src` unreadable / no device reply | `DeviceError` → rc 1 |
| dst set empty after dropping `src` | error `nothing to copy (...)` → rc 2 |
| user answers no at the prompt | `aborted; nothing written` → rc 1, no write |
| read-back verify fails on a dst | `VerificationError` from `load` → rc 1 (backup already taken) |
| invalid slot number | argparse rejects (choices 1–4) |

## Testing (all via `MockTransport`, no hardware)

- **model:** `reslot` sets `raw[0]` and `.slot` to dst, re-decodes values, leaves
  bytes 1–12 intact; empty-raw raises `ValueError`.
- **cli copy:**
  - `copy 1 3 --yes` → slot 3 equals slot 1's payload with `raw[0] == 3`.
  - `copy 1 2 3 4 --yes` → slots 2/3/4 get slot 1's content; slot 1 unchanged.
  - confirm path: `input` → "y" writes; `input` → "n" aborts (rc 1, no write).
  - `copy 1 1 --yes` → rc 2 (nothing to copy).
  - duplicate dsts (`copy 1 2 2 --yes`) → slot 2 written once.
- **regression:** existing `preset apply` tests still pass after the `reslot`
  refactor.

## Documentation

- Add `copy` to the README usage block.
- Flip the "Copy preset (read slot A → write slot B)" row in
  `docs/feature-list.md` to ✅ (`copy`).
