# LPK25 mk1 CLI — Backup Management — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** `device.backup()/restore()`, the `library._config_dir` resolver,
  and the `_confirm` / `_preview` CLI helpers. Tracks issue #10.

## Problem

`backup` writes timestamped files and `restore <file>` needs an explicit path.
There's no way to see what backups exist, roll back to the most recent one, or
stop the auto-backup directory (every write makes one) from growing forever.
Backups also currently land in a cwd-relative `./backups`, so they depend on
where you happened to run the command.

## Goal

A small backup-management surface: a stable backup location, `backup list`,
`restore --latest`, and `backup prune --keep N`.

## Non-goals (YAGNI)

- Compression / rotation policies beyond keep-N.
- Per-slot or selective restore (that's `set`/`load`).
- `--older-than` pruning (revisit if needed).

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Location | **`$LPK25_BACKUP_DIR`** (default `<config>/lpk25/backups`), default for **all** backups incl. auto-backup; `-o/--dir` overrides | discoverable from any cwd; consistent with preset/bank dirs |
| Command shape | **`backup save \| list \| prune`** subcommands; bare `lpk25 backup` still saves | backward-compatible, room to grow |
| Prune | **`--keep N`** (keep newest N), confirm prompt + `-y` | covers the common case; deletion warrants a prompt |
| Restore latest | **`restore --latest`** (file arg becomes optional) | matches the issue; no new command |
| List | newest-first, name + per-slot channel summary | quick to scan |

## CLI surface

```
lpk25 backup [save] [-o DIR]          # save a timestamped backup (default action)
lpk25 backup list [-o DIR]            # list backups, newest first
lpk25 backup prune --keep N [-y] [-o DIR]
lpk25 restore --latest [--no-verify]  # restore the most recent backup
lpk25 restore <file> [--no-verify]    # restore a specific file (unchanged)
```

- `-o/--output/--dir` overrides the backup directory everywhere (default
  `$LPK25_BACKUP_DIR`).
- `prune` keeps the newest `N` and deletes the rest, after a confirmation
  (skipped with `-y`). `--keep 0` is allowed (delete all), still prompts.
- `restore --latest` honors the global `--dry-run` (previews, writes nothing).

## Architecture / components

```
src/lpk25/
  library.py  + backup_dir(); + list_backup_paths / latest_backup / prune_backups
  device.py   default backup dir -> library.backup_dir() (sentinel, not None);
              __init__ stores self.backup_dir; restore() uses the default
  cli.py      cmd_backup -> save/list/prune; cmd_restore + --latest;
              backup subparser group; restore file arg optional
  conftest.py autouse fixture isolates $LPK25_{BACKUP,PRESET,BANK}_DIR to tmp
```

### `library.py`

```python
def backup_dir() -> str: return _config_dir("LPK25_BACKUP_DIR", "backups")

def list_backup_paths(directory=None) -> list[str]:
    # full paths of lpk25-backup-*.json, newest first (by mtime, name tiebreak)

def latest_backup(directory=None) -> str | None
def prune_backups(keep, directory=None) -> list[str]   # deletes, returns removed
```

### `device.py`

A sentinel default means "use the configured backup dir", since `None` already
means "skip backup":

```python
_DEFAULT_BACKUP_DIR = object()
# __init__: self.backup_dir = library.backup_dir()
# send_program/load/backup: dir = self.backup_dir if arg is _DEFAULT else arg
# restore(): self.load(preset, verify=verify)   # default dir
```

Auto-backup (every write) now lands in `$LPK25_BACKUP_DIR` by default.

### `conftest.py`

Add an autouse fixture pointing `LPK25_BACKUP_DIR` / `LPK25_PRESET_DIR` /
`LPK25_BANK_DIR` at a per-test tmp dir, so the new default never writes to the
real home during tests (per-test `monkeypatch.setenv` still overrides).

## Error handling

| Case | Behaviour |
|------|-----------|
| `list` / `prune` with no backups | `(no backups)` / `nothing to prune` → rc 0 |
| `restore --latest` with no backups | error → rc 2 |
| `restore` with neither file nor `--latest` | error → rc 2 |
| user answers no at prune prompt | `aborted; nothing deleted` → rc 1 |
| `--keep` negative | `LibraryError` → rc 1 |

## Testing (all offline)

- **library:** `backup_dir` honors env; `list_backup_paths` newest-first (mtime
  controlled via `os.utime`); `latest_backup`; `prune_backups(keep)` deletes the
  right files and returns them; empty dir → `[]`.
- **cli:** bare `backup` writes into the configured dir; `backup list` shows
  newest-first; `backup prune --keep 1 -y` removes the rest; prune confirm-no
  aborts (nothing deleted); `restore --latest` restores the newest backup's
  content onto the mock; `restore` with no args errors.
- **regression:** existing write tests still pass with the new default location
  (isolated by the conftest fixture).

## Documentation

- README: document `$LPK25_BACKUP_DIR`, `backup list/prune`, `restore --latest`.
- `docs/feature-list.md`: note backup management under Safety.
- Issue #10 closed by the implementing PR.
