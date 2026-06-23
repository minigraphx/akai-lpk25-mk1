# LPK25 mk1 CLI — Named Banks — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** `library.py` (single-program presets), `model.Preset` (already a
  multi-program unit), `device.dump()`/`device.load()`, the `_preview` dry-run
  helper, and `render.format_presets_table`. Tracks issue #8.

## Problem

The preset library stores **single** programs (`preset save/apply/list`), and
`backup` writes anonymous timestamped snapshots. There's no way to save the
**whole device** (all 4 slots) under a memorable name and recall it later
("live", "studio", "default", …). A `Preset` already models 4 programs with JSON
save/load — we just need a named library for it.

## Goal

`lpk25 bank save|apply|list|show|delete <name>` — a named library of full
4-program device states, parallel to the single-program `preset` library.

## Non-goals (YAGNI)

- Editing individual slots inside a bank (use `edit`/`set`, then re-save).
- Merging/partial application of selected slots only.
- Cloud/shared library sync.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | **separate dir**: `LPK25_BANK_DIR` (default `<config>/lpk25/banks`) | keeps single-program presets and full banks cleanly separated; no name clashes in `list` |
| `apply` safety | **confirm prompt** (`-y` skips) + auto-backup + read-back verify; honors global `--dry-run` | applying overwrites all 4 slots — significant, like `copy` |
| Subcommands | **save / apply / list / show / delete** | full lifecycle |
| Format | reuse `Preset` JSON (same as `dump`/`backup`) | interoperable with `dump -o` / `restore` |
| Library code | refactor shared dir/path helpers; banks reuse `Preset.save/load` | DRY with the preset library |

## CLI surface

```
lpk25 bank save <name> [--force]            # dump all 4 slots -> named bank
lpk25 bank apply <name> [-y] [--no-verify]  # write all 4 slots (confirm + backup + verify)
lpk25 bank list                             # list banks (name + program count)
lpk25 bank show <name>                       # print the bank's 4-program table
lpk25 bank delete <name>                     # remove a saved bank
```

- `save`: `dev.dump()` → `library.save_bank(name, preset)`. Refuses to overwrite
  unless `--force`.
- `apply`: `library.load_bank(name)` → confirm (unless `-y`) → `dev.load(preset)`
  (one backup, per-slot write + verify). With global `--dry-run`, print the
  per-slot diff via `_preview` and write nothing (no prompt).
- `list`: `name (N programs)` per bank, or `(no banks)`.
- `show`: `render.format_presets_table(preset)`.
- `delete`: remove `<name>.json`; error if missing.

## Architecture / components

```
src/lpk25/
  library.py  refactor: _config_dir(env, subdir) shared by preset_dir/bank_dir;
              + bank_dir(), save_bank, load_bank, list_bank_names, list_banks,
                delete_bank  (reuse _validate_name / _path)
  cli.py      + cmd_bank, + `bank` subparser group (save/apply/list/show/delete)
  device.py   unchanged (dump/load reused)
```

### `library.py`

```python
def _config_dir(env_var: str, subdir: str) -> str:
    env = os.environ.get(env_var)
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "lpk25", subdir)

def preset_dir() -> str: return _config_dir("LPK25_PRESET_DIR", "presets")
def bank_dir() -> str:   return _config_dir("LPK25_BANK_DIR", "banks")
```

Bank functions mirror the preset ones but operate on a whole `Preset`:
`save_bank(name, preset, force=False, directory=None)`,
`load_bank(name, directory=None) -> Preset`,
`list_bank_names`, `list_banks() -> list[(name, Preset)]`,
`delete_bank(name, directory=None) -> str`. All reuse `_validate_name` and
raise `LibraryError` (already used by the preset CLI handler).

### `cli.cmd_bank` flow (apply)

```
preset = library.load_bank(name)
dev = _make_device(args)
if args.dry_run: return _preview(dev, preset.programs)   # no prompt, no write
if not args.yes and not _confirm("About to overwrite N slot(s) from bank '…'. Proceed? [y/N] "):
    return 1   # "aborted; nothing written"
results = dev.load(preset, verify=not args.no_verify)
```

Confirmation precedes the write (and the backup inside `load`); `_make_device`
itself does no I/O.

## Error handling

| Case | Behaviour |
|------|-----------|
| `save` over an existing bank without `--force` | `LibraryError` → rc 1 (`already exists`) |
| `apply`/`show`/`delete` unknown bank | `LibraryError` → rc 1 (`not found. Available: …`) |
| corrupt bank file | `LibraryError` → rc 1 (`unreadable`) |
| invalid name (path separators) | `LibraryError` via `_validate_name` |
| user answers no at `apply` prompt | `aborted; nothing written` → rc 1, no write |

## Testing (all offline)

- **library:** save→load round-trips a 4-program `Preset`; overwrite guard +
  `--force`; `list_bank_names`/`list_banks`; `delete_bank` removes and then
  errors; banks honor `LPK25_BANK_DIR`; banks and presets don't see each other.
- **cli bank (via `MockTransport`, `LPK25_BANK_DIR=tmp`):**
  - `bank save live` then `bank apply live` round-trips all 4 slots; slot-echo
    bytes correct.
  - `apply` confirm: `input→y` writes; `input→n` aborts (rc 1, nothing written).
  - `apply -y` skips the prompt; `--dry-run` previews and writes nothing (no prompt).
  - `list` shows the bank; `list` empty → `(no banks)`.
  - `show` prints the 4-row table; `delete` removes it; re-`delete` errors.

## Documentation

- Add the `bank` commands + `$LPK25_BANK_DIR` to the README usage.
- Add a "Named banks" feature bullet; flip the relevant `docs/feature-list.md`
  row if present.
- Issue #8 closed by the implementing PR.
