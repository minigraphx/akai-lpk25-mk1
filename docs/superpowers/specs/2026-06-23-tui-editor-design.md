# LPK25 mk1 CLI — Interactive TUI Editor — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** the existing `device`, `codec`, `model`, `library`, `render`, and
  `mididecode` layers — no protocol logic duplicated. Tracks issue #15.

## Problem

Editing programs today means one-shot CLI commands (`edit`, `show`, `copy`,
`preset`/`bank`). For iterative, hands-on tweaking — change a field, hear it,
change another — that round-trip is clumsy. A terminal UI gives most of the
ergonomics of a GUI (navigate, see everything at once, edit in place) while
staying in the keyboard-driven, dependency-light spirit of the tool.

## Goal

`lpk25 tui` — a navigable terminal editor that shows all four programs and
their confirmed fields in a grid, lets you edit fields in place, and writes
changes back through the existing auto-backup + read-back-verify path. It also
recalls programs on the device, loads/saves presets and banks via the library,
and can show a live decoded-MIDI panel — all built on the existing layers.

## Non-goals (YAGNI)

- A mouse-driven interface — keyboard only.
- Editing unmapped/unknown bytes — only the mapped `codec` fields are editable;
  unknown bytes are preserved verbatim (the codec already guarantees this).
- A second MIDI-monitor implementation — the panel reuses `mididecode`.
- Multi-device / multi-port management — one device per session, as today.
- Theming/colour configuration — a single sensible scheme.

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Toolkit | **stdlib `curses`** | zero new deps; ships with CPython on macOS + Linux; matches the project's dependency-light core |
| Architecture | **pure controller + thin view** | all state/logic in a curses-free `EditorController` (fully unit-testable); curses confined to drawing + key reads |
| Workflow optimised for | **live tweaking at the keyboard** | snappy navigation, one-key commit |
| Commit model | **explicit per-slot write** (`w`) | edits stay in memory with a dirty marker; one key writes the current slot through backup + verify; batches a slot's edits into one device write |
| Layout | **grid, all 4 programs visible** | at-a-glance, jump anywhere fast; reuses the `show` table mental model |
| Field schema | **`codec.LPK25_MK1_FIELDS`** | single source of truth for columns, value stepping, and validation — shared with `edit` |
| Library load/save | **in-TUI**, via name prompt / pick-list overlays | full-issue scope; thin wrappers over `library` |
| MIDI monitor | **toggleable bottom pane** (`m`), off by default | keeps editing primary; background reader thread; reuses `mididecode` |
| Offline (`--mock`) | **fully editable in memory** | richer than the issue's read-only minimum; monitor shows "no MIDI input" |

## CLI surface

### `lpk25 tui [--mock]`

Opens the editor on the connected device (or the in-memory mock with `--mock`).
Requires an interactive terminal: if stdout is not a TTY, print an error and
exit `2`. `curses` is imported lazily inside `cmd_tui` so the other commands
never pay for it.

## Interaction model

```
 lpk25 tui — slot 3 · arp_mode                    [* unsaved: 3]   [MOCK]
   slot  ch  oct  trans  arp   mode  div   clock latch tempo taps aoct
 ▶  1     1    0      0  off     up  1/8    int   off   120    4    1
    2     1   -1      0   on     up  1/8    int   off   120    4    1
    3 *   5    0      0   on  [excl] 1/16   ext   on    128    4    2
    4     1    0      0  off     up  1/8    int   off   120    4    1

 ↑↓ slot   ←→ field   -/+ change   ⏎ type-in   w write slot   a activate
 s/l preset   b/B bank   r reload   m monitor   ? help   q quit
 ── monitor (m) ───────────────────────────────────────────────
 ch1 Note On  C4 vel 100
 ch1 Note Off C4 vel 0
```

- The focused cell (here slot 3 / `mode`) is drawn in reverse video.
- `▶` marks the active program; `*` marks a slot with unsaved edits; the header
  echoes the focused field name and the set of unsaved slots.

### Keybindings

| Key | Action |
|-----|--------|
| `↑` / `↓` | move between slots (rows), clamped |
| `←` / `→` | move between fields (columns), clamped |
| `-` / `+` | step the focused value: enum cycles, bool toggles, int/`u14` ±1 within `lo`,`hi` |
| `[` / `]` (or PgDn/PgUp) | coarse step ±10 for int/`u14` fields |
| `Enter` | inline type-in for numeric fields (e.g. set tempo to 140); validated by `codec` |
| `u` | undo edits on the current slot (revert to original) |
| `w` | write the current slot (auto-backup + read-back verify) |
| `W` | write all dirty slots |
| `a` | activate (recall) the current slot on the device |
| `r` | reload all programs from the device (confirm if unsaved) |
| `s` / `l` | save / load a single-program **preset** for the current slot |
| `b` / `B` | save / load a full 4-program **bank** |
| `m` | toggle the MIDI monitor pane |
| `?` | toggle the help/legend |
| `q` | quit (confirm if unsaved) |

Value stepping is derived entirely from each `codec.Field`: `int`/`u14` clamp to
`lo`,`hi`; `bool` toggles; `enum` cycles its codes (wrapping). Validation reuses
`Field.encode_into`, which already raises `CodecError` out of range.

## Architecture / components

```
src/lpk25/tui/
  __init__.py
  controller.py   PURE (no curses): edit state, cursor, dirty tracking, value
                  stepping, validation, write/activate/reload/library actions
  view.py         curses rendering: grid + status + help + monitor pane + overlays
  monitor.py      background MIDI reader thread → bounded deque of decoded lines
  app.py          curses main loop: wire controller + view + monitor + device
src/lpk25/
  cli.py          cmd_tui + `tui` subparser; TTY guard; lazy curses import
```

### `controller.py` — `EditorController`

```python
@dataclass
class RowView:
    slot: int
    values: dict[str, object]   # decoded display values (codec.decode_program)
    dirty: bool
    active: bool

class EditorController:
    def __init__(self, dev: Device, preset: Preset, active_slot: int | None): ...
    # state: edited[4] (Program), original[4] (Program), cursor(slot_idx, field_idx),
    #        active_slot. The editable columns and their left-to-right order
    #        follow render's column list (minus the synthetic "slot"); each
    #        column resolves to its codec.Field by name for stepping/validation.

    def rows(self) -> list[RowView]
    def focused_field(self) -> codec.Field
    def header(self) -> str               # "slot N · <field>" + unsaved summary

    def move(self, d_slot: int, d_field: int) -> None      # clamp to grid
    def step(self, delta: int) -> None                     # change focused value
    def set_value(self, text: str) -> None                 # type-in; raises CodecError
    def undo_slot(self) -> None

    def write_current(self) -> WriteResult                 # dev.send_program
    def write_all_dirty(self) -> list[WriteResult]
    def activate_current(self) -> int | None               # dev.activate
    def reload(self) -> None                               # dev.dump + get_active_program

    def save_preset(self, name: str, force: bool = False) -> str
    def load_preset_into_current(self, name: str) -> None  # marks slot dirty
    def save_bank(self, name: str, force: bool = False) -> str
    def load_bank(self, name: str) -> None                 # replaces all 4, marks dirty
```

The controller is curses-free but device-aware; the `Device` is injected, so
every device-touching method is exercised offline with `Device(MockTransport())`.
"Dirty" is `edited[i].raw != original[i].raw`. Writes clear dirty by copying the
written program into `original`.

### `view.py` (thin curses)

```python
def draw(stdscr, controller, monitor, show_monitor: bool, show_help: bool, message: str) -> None
def prompt(stdscr, label: str) -> str | None          # inline text entry; Esc → None
def choose(stdscr, title: str, options: list[str]) -> str | None   # pick-list; Esc → None
```

Drawing reuses `render`'s column order and short labels for the header row. The
focused cell uses `curses.A_REVERSE`. `prompt`/`choose` back the library
name-entry and selection overlays.

### `monitor.py` — `MidiMonitor`

```python
class MidiMonitor:
    def __init__(self, transport, maxlen: int = 200): ...
    def start(self) -> None        # daemon thread: read input frames, decode, append
    def stop(self) -> None
    def lines(self, n: int) -> list[str]
    @property
    def available(self) -> bool    # False when the transport has no MIDI input
```

The reader thread loops on the transport's input read with a short timeout,
decodes each frame via `mididecode.decode_message`, and appends to a bounded
`deque`. Offline / without the `[midi]` extra, `available` is False and the pane
shows "no MIDI input (offline)". The decode-and-buffer logic is unit-tested via
an injected fake-input transport (not `MockTransport`, whose `receive` returns
the editor's own reply frames).

### `app.py`

```python
def run(transport, mock: bool) -> int:
    dev = Device(transport)
    controller = EditorController(dev, dev.dump(), dev.get_active_program())
    monitor = MidiMonitor(transport)
    return curses.wrapper(_loop, controller, monitor) or 0
```

`_loop` reads keys, dispatches to the controller/monitor, sets a transient
status message, and redraws. `curses.wrapper` guarantees terminal restoration.

## Offline degradation

| Case | Behaviour |
|------|-----------|
| `--mock` | full in-memory editing; writes hit the mock store and verify passes; monitor pane shows "no MIDI input (offline)" |
| real run without `[midi]` | `_make_transport` errors as today — a port is required to reach hardware |
| stdout not a TTY (piped) | error + exit `2` |
| terminal too small | draw what fits; never crash |

## Error handling / edge cases

| Case | Behaviour |
|------|-----------|
| `VerificationError` / `DeviceError` on write | status-line message; slot stays dirty; no crash |
| `CodecError` on type-in (range/enum) | status-line message; value unchanged |
| library overwrite (`save_preset`/`save_bank` exists) | confirm prompt before passing `force=True` |
| `q` / `reload` with unsaved edits | confirm prompt; cancel keeps editing |
| exception inside the loop | `curses.wrapper` restores the terminal; the error is surfaced after restore |
| unknown/unverified enum code | already passes through `codec` as an int; displayed as the int |

## Testing (all offline, no hardware)

- **controller (the bulk):** navigation clamp at edges; `step` per kind — int
  clamps `lo`/`hi`, enum cycles (including wrap), bool toggles, tempo `u14`
  clamps 30/240; dirty set on edit, cleared on write, reverted by `undo_slot`;
  `write_current` and `write_all_dirty` against `Device(MockTransport())`
  (mock store updated, verified); `activate_current` flips the mock active slot;
  `reload` discards edits; `set_value` valid and invalid (`CodecError`);
  library `save_preset`/`load_preset_into_current` and `save_bank`/`load_bank`
  using temp directories.
- **monitor:** fake-input transport → decoded lines; ring buffer caps at
  `maxlen`; `available` False without input.
- **cli:** `lpk25 tui` with non-TTY stdout → exit `2` + message (monkeypatch
  `isatty`).
- The curses drawing layer (`view`/`app` loop) is the only untested code and is
  kept deliberately thin.

## Documentation

- README: add the `lpk25 tui` usage line and a short keybinding summary.
- `docs/feature-list.md`: mark the interactive TUI editor ✅.
- Issue #15 closed by the implementing PR.
